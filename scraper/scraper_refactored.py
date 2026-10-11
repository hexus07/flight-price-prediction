import sys
import datetime
import argparse
import logging 
from typing import List, Tuple, Generator, Dict, Optional
import gc

from time import sleep
import pandas as pd

from google_flights import create_filter, get_flights_from_filter, FlightData, Passengers, TFSData, DecodedResult
from itertools import chain, islice

import sqlite3

from regions import construct_routes, REGIONS_AIRPORTS

from time import sleep
import tracemalloc



INVALID_VALUES = {None, "", "None", "unknown"} 
def safe_get(value, default=None, invalid_values=INVALID_VALUES):
    """
    Safely get a value, returning a default if the value is invalid.
    
    Args:
        value: The value to check.
        default: The default value to return if the value is invalid.
        invalid_values: A set of values considered invalid.
        
    Returns:
        The value if valid, otherwise the default.
    """
    try:
        if value in invalid_values:
            return default
        return value
    except Exception as e:
        logging.error(f"Error in safe_get: {e}")
        return default
    

def get_datetime(date, time) -> datetime.datetime:
    """
    Given `date` (iterable of [year, month, day]) and `time` (list of ints),
    
    returns a datetime.datetime. If `time` is not a list, returns None.
    """

    if isinstance(time, list):
        if len(time) == 1:
            return datetime.datetime.combine(datetime.date(*date), datetime.time(hour=time[0]))
        elif len(time) == 2 and time[0] is None:
            return datetime.datetime.combine(datetime.date(*date), datetime.time(minute=time[1]))
        else:
            return datetime.datetime.combine(datetime.date(*date), datetime.time(hour=time[0], minute=time[1]))
    else:
        return None


class FlightLegParser:
    def __init__(self, leg):
        self.leg = leg
        

    @property
    def airline_code(self) -> str:
        return getattr(self.leg, "airline", "")
    
    @property
    def flight_number(self) -> str:
        return getattr(self.leg, "flight_number", "")
    
    @property
    def airline_name(self) -> str:
        return getattr(self.leg, "airline_name", "")
    
    @property
    def departure_datetime(self) -> datetime.datetime:
        date = getattr(self.leg, "departure_date", None)
        time = getattr(self.leg, "departure_time", None)
        if date and time:
            result = get_datetime(date, time)
            if result is not None:
                return result
        raise ValueError("Departure date or time is missing")
    
    
    @property
    def departure_date(self) -> datetime.date:
        date = self.departure_datetime.date()
        return date if date else None
    
    @property
    def arrival_datetime(self) -> datetime.datetime:
        date = getattr(self.leg, "arrival_date", None)
        time = getattr(self.leg, "arrival_time", None)
        if date and time:
            result = get_datetime(date, time)
            if result is not None:
                return result
        raise ValueError("Arrival date or time is missing")

    @property
    def leg_id(self) -> str:
        return f"{self.airline_code}{self.flight_number}-{self.departure_datetime.isoformat()}"

    @property
    def departure_airport(self) -> str:
        return getattr(self.leg, "departure_airport", "")
    
    @property
    def arrival_airport(self) -> str:
        return getattr(self.leg, "arrival_airport", "")
    
    @property
    def operating_airline(self) -> str:
        return getattr(self.leg, "operator", None)

    @property
    def operating_aircraft(self) -> str:
        return getattr(self.leg, "aircraft", None)

    @property
    def travel_time(self) -> int:
        return getattr(self.leg, "travel_time", 0)
    
    @property
    def seat_pitch_short(self) -> int:
        return getattr(self.leg, "seat_pitch_short", None)
    @property
    def seat_pitch_type(self) -> str:
        return getattr(self.leg, "seat_type", None)
    @property
    def emissions(self) -> int:
        return getattr(self.leg, "emissions", 0)
    
    def parse_flight_features(self) -> dict:
        """
        Parses flight features from the leg into structured binary/int flags.

        Returns:
            dict: Parsed features with int flags.
        """
        FEATURE_KEYS = [
            "in_seat_power_usb",
            "in_seat_power",
            "usb_outlet",
            "on_demand_video",
            "streaming_media"
        ]
        features = getattr(self.leg, "features", {})
        feature_data = {key: 1 if getattr(features, key, None) == 'included' else 0 for key in FEATURE_KEYS}

        wifi_val = getattr(features, "wifi", '0')
        if wifi_val == 'for free':
            feature_data["wifi"] = 1
        elif wifi_val == 'for fee':
            feature_data["wifi"] = 2
        else:
            feature_data["wifi"] = 0
        return feature_data
    
class FlightItineraryParser:
    def __init__(self, itinerary, metadata):
        self.itinerary = itinerary
        self.metadata = metadata
        self.itinerary_summary = getattr(itinerary, "itinerary_summary", None)
        self.flights = getattr(itinerary, "flights", [])
        self.layovers = getattr(itinerary, "layovers", [])


    @property
    def flight_number(self) -> str:
        return getattr(self.itinerary_summary, "flights", "")
    
    @property
    def departure_airport(self) -> str:
        return getattr(self.itinerary, "departure_airport", "")
    
    @property
    def arrival_airport(self) -> str:
        return getattr(self.itinerary, "arrival_airport", "")
    
    @property
    def departure_datetime(self) -> datetime.datetime:
        date = getattr(self.itinerary, "departure_date", None)
        time = getattr(self.itinerary, "departure_time", None)
        if date and time:
            result = get_datetime(date, time)
            if result is not None:
                return result
        raise ValueError("Invalid departure date or time")
    
    
    @property
    def departure_date(self) -> datetime.date:
        date = self.departure_datetime.date()
        return date if date else None
    @property
    def arrival_datetime(self) -> datetime.datetime:
        date = getattr(self.itinerary, "arrival_date", None)
        time = getattr(self.itinerary, "arrival_time", None)
        if date and time:
            result = get_datetime(date, time)
            if result is not None:
                return result
        raise ValueError("Arrival date or time is missing")
    
    @property
    def airline_names(self) -> str:
        return ', '.join(getattr(self.itinerary, 'airline_names', []))

    @property
    def region_from(self) -> str:
        return self.metadata.get("regions")[0]

    @property
    def region_to(self) -> str:
        return self.metadata.get("regions")[1]

    @property
    def travel_time(self) -> int:
        return getattr(self.itinerary, "travel_time", 0)
    
    @property
    def layover_time(self) -> int:
        if hasattr(self.layovers, "layover_time"):
            return getattr(self.layovers, "layover_time", 0)
        return 0
    
    @property
    def seat_type(self) -> str:
        return self.metadata.get("seat_type", "economy")
    @property
    def total_emissions(self) -> int:
        return sum(getattr(flight, "emissions", 0) or 0 for flight in self.flights)
    
    @property
    def is_best(self) -> bool:
        return self.metadata.get("is_best", True)
    
    @property
    def itinerary_id(self) -> str:
        return f"{self.flight_number}-{self.departure_datetime.isoformat()}-{self.departure_airport}-{self.arrival_airport}"

    @property
    def price(self) -> float:
        return getattr(self.itinerary_summary, "price", None)


    def parse_itinerary(self) -> Dict:
        """
        Parses the itinerary into a dictionary format.
        
        Returns:
            dict: Parsed itinerary data.
        """
        return {
            "itinerary_id": self.itinerary_id,
            "departure_date": self.departure_date.isoformat(),
            "region_from": self.region_from,
            "region_to": self.region_to,
            "seat_type": self.seat_type,
            "is_best": self.is_best,
        }

    def parse_legs(self) -> List[Dict]:
        leg_records = []
        for leg in self.flights:
            leg_parser = FlightLegParser(leg)
            feature_data = leg_parser.parse_flight_features()
            leg_records.append({
                    "itinerary_id": self.itinerary_id,
                    "airline_code": leg_parser.airline_code,  # Handle missing airline code
                    "flight_number": leg_parser.flight_number,
                    "airline_name": leg_parser.airline_name,
                    "operator": leg_parser.operating_airline,
                    "aircraft": leg_parser.operating_aircraft,
                    "src": leg_parser.departure_airport,
                    "dst": leg_parser.arrival_airport,
                    "departure_datetime": leg_parser.departure_datetime.isoformat(),
                    "arrival_datetime": leg_parser.arrival_datetime.isoformat(),
                    "travel_time": leg_parser.travel_time,
                    "seat_pitch_short": leg_parser.seat_pitch_short,
                    "seat_pitch_type": leg_parser.seat_pitch_type,
                    "emissions": leg_parser.emissions,
                    "in_seat_power_usb": feature_data.get("in_seat_power_usb"),
                    "in_seat_power_ac": feature_data.get("in_seat_power"),
                    "usb_outlet": feature_data.get("usb_outlet"),
                    "on_demand_media": feature_data.get("on_demand_video"),
                    "streaming_media": feature_data.get("streaming_media"),
                    "wifi": feature_data.get("wifi"),
                })
            
        return leg_records
    
    def parse_prices(self) -> List[Dict]:
        """
        Parses the price from the itinerary + features.
        Returns:
            List[Dict]: Price record.
        """
        return {
            "itinerary_id": self.itinerary_id,
            "price_datetime": datetime.datetime.now().isoformat(),
            "days_to_departure": (self.departure_datetime - datetime.datetime.now()).days if self.departure_datetime else None,
            "day_of_week": datetime.date.today().strftime("%A"),
            "time_window": self.metadata.get("time_window"),
            "price": self.price
        }


        
MAX_DEFAULT_EXCEPTIONS = 5

def retry_collect_flight_data(
        flight_filter: TFSData,
        max_attempts: int = MAX_DEFAULT_EXCEPTIONS,
        ) -> Optional[DecodedResult]:
    """
     Collect flight data from the given filter.

    Args:
        filter (TFSData): Filter criteria for flights.
        max_attempts (int, optional): Maximum number of exceptions allowed. Defaults to 5.
    Returns:
        DecodedResult: parsed flight data or None if failed.
    """

    for attempt in range(1, max_attempts + 1):
        try:
            data = get_flights_from_filter(flight_filter, data_source='js', mode='common')
            return data
        except Exception as e:
            logging.error(f"Error collecting data on attempt {attempt}: {e}")
            sleep(2)

    logging.error(f"Failed to collect data after {max_attempts} attempts.")
    return None



def parse_flight_data(
        data: DecodedResult,
        metadata: Dict[str, str],
        ) -> Tuple[List[Dict], List[Dict], List[Dict]]:
    """
    Parses flight data from the decoded result into itinerary, leg, and price records.
    Args:
        data (DecodedResult): Raw flight data.
        metadata (dict): Metadata containing info like trip type, regions.

    Returns:
        Tuple[List[Dict], List[Dict], List[Dict]]: itinerary, leg, and price records lists.
    """
    
    # Data extraction
    itin_records = []
    leg_records = []
    price_records = []

    # check on 
    if not data or (not data.best and not data.other):
        raise ValueError("No flight data found")    

    flight_itineraries = chain(data.best or [], data.other or [])

    for flight_itinerary in flight_itineraries:
        if flight_itinerary is None:
            logging.error("No flight_itinerary is found")
            continue

        # Parse itinerary
    
        metadata["is_best"] = flight_itinerary not in data.other
        parser = FlightItineraryParser(flight_itinerary, metadata)
        try:
            leg_records.extend(parser.parse_legs())
            price_records.append(parser.parse_prices())
            # if there's no leg info, itinerary would be skipped
            itin_records.append(parser.parse_itinerary())
        except ValueError as e:
            logging.error(f"Error parsing flight itinerary via parser: {e}")
            continue

    return itin_records, leg_records, price_records


def itineraries_list(offsets: List[int]) -> pd.DataFrame:
    """
    Returns a list of itineraries from the database for the target dates

    """
    db_path = "flights.db"  # Replace with your database path
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    ensure_indexes(conn)
    
    today = datetime.date.today()
    target_dates = [(today + datetime.timedelta(days=o)).isoformat() for o in offsets]

    # Now use these dates in your SQL query:
    placeholders = ','.join('?' for _ in target_dates)
    query = f"""
        SELECT itinerary_id, departure_date
        FROM itin
        WHERE departure_date IN ({placeholders})
    """
    cursor.execute(query, target_dates)
    rows = cursor.fetchall()

    itineraries = pd.DataFrame(rows, columns=[col[0] for col in cursor.description])
    conn.close()
    return itineraries

    

def parse_args():
    parser = argparse.ArgumentParser(
        description="Scrape Google Flights data" 
    )
    parser.add_argument(
        "--max_stops",
        type=int,
        default=0,
        choices=[0, 1, 2],
        help="Maximum number of stops for the flight. Must be an integer (0, 1, or 2)."
    )
    parser.add_argument(
        "--window",
        choices=["morning", "midday", "afternoon", "evening"],
        required=False,
        default=None,
        help="Time-of-day bucket for scheduling."
    )
    
    parser.add_argument(
        "--airlines",
        type=str,
        nargs='*',
        required=False,
        help="List of airlines to filter by."
    )

    parser.add_argument(
        "--start_offset",
        type=int,
        default=0,
        help="Skip departure-date offsets smaller than this (to resume a stopped run)."
    )

    parser.add_argument(
        "--end_offset",
        type=int,
        default=None,
        help="Skip departure-date offsets bigger than this. Use the same value as --start_offset to scrape one day."
    )

    return parser.parse_args()

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler("scrape.log"),
            logging.StreamHandler(sys.stdout),
        ]
    )
    return logging.getLogger("google_flights")


def collect_flight_data(
        max_stops: int = 0,
        airlines: Optional[List[str]] = [],
        start_offset: int = 0,
        end_offset: Optional[int] = None
        ):
    """
    Collects flight data for the specified 
    
    Args:
        max_stops (int): Maximum number of stops for the flight.
        airlines (List[str]): List of airlines to filter by.
    """
    all_itin_records = []
    all_leg_records = []
    all_price_records = []


    # Setup logging
    logger = logging.getLogger(__name__)
    

    tHour = datetime.datetime.now().hour
    match tHour:
        case 0 | 1 | 2 | 3 | 4 | 5:
            time_window = "night"
        case 6 | 7 | 8 | 9 | 10 | 11:
            time_window = "morning"
        case 12 | 13 | 14 | 15 | 16:
            time_window = "afternoon"
        case 17 | 18 | 19 | 20 | 21 | 22 | 23:
            time_window = "evening"

    logging.info(f"Collecting flight data for {time_window}.")


    offsets = (
        list(range(1, 8, 1)) +        # daily first week
        list(range(8, 31, 2)) +       # every 2 days next 3 weeks
        list(range(31, 91, 4))        # every 4 days up to 90 days
    )
    if end_offset is not None and start_offset == end_offset:
        offsets = [start_offset]          # single arbitrary day (offset need not be in the list above)
    else:
        offsets = [o for o in offsets if o >= start_offset and (end_offset is None or o <= end_offset)]

    try:
        for offset in offsets:
            # remember sizes, so an unfinished offset can be dropped on Ctrl+C
            n_itin, n_leg, n_price = len(all_itin_records), len(all_leg_records), len(all_price_records)
            routes = construct_routes()
            departure_date = (datetime.datetime.now() + datetime.timedelta(days=offset)).strftime("%Y-%m-%d")
            logging.info(f"Departure date: {departure_date}")   

            for regions, src, dst in routes:
                # skip if source and destination are the same
                if src == dst:
                    dst = REGIONS_AIRPORTS[regions[1]]
                
                logging.info(f"Collecting flights from {src} to {dst} for {departure_date}.")

                # Create filter
                flight_filter = create_filter(
                    flight_data = [FlightData(
                        airlines=airlines,  # Airline codes, empty list means no filter
                        date=departure_date,  # Date of departure
                        from_airport=src,  # Departure airport
                        to_airport=dst,  # Arrival airports
                    )],
                    trip="one-way",  # Trip type
                    passengers=Passengers(adults=1, children=0, infants_in_seat=0, infants_on_lap=0),
                    seat="economy",  # Seat type
                    max_stops=max_stops,  # Maximum number of stops
                )

                # Collect flight data
                data = retry_collect_flight_data(flight_filter)
                
                if data:
                    # Metadata for the current flight
                    metadata = {
                        "regions": regions,
                        "seat_type": "economy",
                        "time_window": time_window,  # Time window for scheduling
                        "is_best": False,  # Default value, can be updated later
                    }
                
                    try:
                        itin_records, leg_records, price_records = parse_flight_data(data, metadata)
                        all_itin_records.extend(itin_records)
                        all_leg_records.extend(leg_records)
                        all_price_records.extend(price_records)
                    except ValueError as e:
                        continue
    except KeyboardInterrupt:
        # drop the half-collected offset, so resuming from it creates no duplicates
        del all_itin_records[n_itin:], all_leg_records[n_leg:], all_price_records[n_price:]
        logger.warning(f"Stopped by user. offset {offset} was not finished and is not saved.")
        logger.warning(f">>> Resume with: python scraper_refactored.py --start_offset {offset}")
        return all_itin_records, all_leg_records, all_price_records

    # Check for missing records which exist in the database for the given offsets
    existing_itineraries = itineraries_list(offsets)
    missing_itineraries = existing_itineraries[~existing_itineraries['itinerary_id'].isin({record['itinerary_id'] for record in all_itin_records})]
    logger.info(f"Missing itineraries number: {missing_itineraries.shape[0]} out of {existing_itineraries.shape[0]}")

    # Write into csv for next moves
    missing_itineraries.to_csv("missing_itineraries.csv", index=False)
    return all_itin_records, all_leg_records, all_price_records


def ensure_indexes(conn):
    """Indexes make look-ups by id/date instant instead of scanning the whole table (created once)."""
    conn.execute("CREATE INDEX IF NOT EXISTS idx_itin_id ON itin(itinerary_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_itin_date ON itin(departure_date)")


def existing_ids(conn, ids, chunk: int = 500) -> set:
    """Return which of `ids` are already in `itin` (queries only those ids, not the whole table)."""
    ids = list(set(ids))
    found = set()
    for i in range(0, len(ids), chunk):
        part = ids[i:i + chunk]
        placeholders = ",".join("?" * len(part))
        rows = conn.execute(f"SELECT itinerary_id FROM itin WHERE itinerary_id IN ({placeholders})", part)
        found.update(r[0] for r in rows)
    return found


def save_to_database(itineraries: pd.DataFrame, legs: pd.DataFrame, prices: pd.DataFrame, db_path: str = "flights.db"):
    """
    Saves the given DataFrame to a SQLite database table, ensuring unique entries.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    ensure_indexes(conn)

    # Which of the collected itinerary_ids are already in the DB (looks up only these ids)
    existing = existing_ids(conn, itineraries['itinerary_id'])

    # Filter the records in 'itineraries' that are not already in the DB and save them
    new_itineraries = itineraries[~itineraries['itinerary_id'].isin(existing)]
    print(f"Saving {new_itineraries.shape[0]} new itineraries to the database.")
    new_itineraries.to_sql('itin', conn, if_exists='append', index=False)


    # Filter the records in 'legs' that do not already in 'existing_itineraries' and save them
    new_legs = legs[~legs['itinerary_id'].isin(existing)]

    print(f"Saving {new_legs.shape[0]} new legs to the database.")
    new_legs.to_sql('legs', conn, if_exists='append', index=False)

    # Save all prices
    prices.to_sql('prices', conn, if_exists='append', index=False)

    # Commit the transaction to save changes
    conn.commit()

    # Close the connection
    conn.close()


def display_top(snapshot, key_type='lineno', limit=10):
    snapshot = snapshot.filter_traces((
        tracemalloc.Filter(False, "<frozen importlib._bootstrap>"),
        tracemalloc.Filter(False, "<unknown>"),
    ))
    top_stats = snapshot.statistics(key_type)
    print(f"\nTop {limit} lines")
    for stat in top_stats[:limit]:
        print(stat)



def log_df_as_artifact(df: pd.DataFrame, name: str):
    markdown_table = df.head(2)
    logging.info(f"DataFrame {name} preview:\n{markdown_table}")




# --------------------------------------------------------------------------------
# The main flow
# --------------------------------------------------------------------------------

def main():
    args = parse_args()
    logger = setup_logging()


    # 1) Measure memory usage
    tracemalloc.start()
    snapshot1 = tracemalloc.take_snapshot()


    # 2) Collect flight data
    all_itin_records, all_leg_records, all_price_records = collect_flight_data(
        max_stops=args.max_stops,
        airlines=args.airlines or [],
        start_offset=args.start_offset,
        end_offset=args.end_offset
    )
    logger.info("Flight data collection completed.")

    # 4) Convert to DataFrames
    itin_df = pd.DataFrame(all_itin_records)
    leg_df = pd.DataFrame(all_leg_records)
    price_df = pd.DataFrame(all_price_records)

    # 5) Log DataFrames as artifacts
    log_df_as_artifact(itin_df, "itineraries_preview")
    log_df_as_artifact(leg_df, "legs_preview")
    log_df_as_artifact(price_df, "prices_preview")

    # 6) Backup prices to parquet
    price_df.to_parquet("prices_latest.parquet", index=False)

    # 7) Submit save_to_database and block on its completion
    try:
        save_to_database(itin_df, leg_df, price_df)
        logger.info("Data saved to database successfully.")
    except Exception as e:
        logger.error(f"Error saving data to database: {e}")

    # 8) Take a second memory snapshot, compare to the first,
    snapshot2 = tracemalloc.take_snapshot()
    
    print("Identifying top lines that grew in memory:")
    stats = snapshot2.compare_to(snapshot1, 'lineno')
    for stat in stats[:5]:
        print(stat)

    # (Optional) See overall top allocation spots:
    display_top(snapshot2, limit=5)

    tracemalloc.stop()
    # 9) Clean up memory
    gc.collect()
    logger.info("Memory cleanup completed.")

    sleep(100)


if __name__ == "__main__":
    main()