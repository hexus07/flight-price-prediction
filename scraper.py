#!/usr/bin/env python3
import sys
import datetime
import argparse
import logging 
from typing import List, Tuple, Generator, Dict, Optional
import gc

from time import sleep, time
import pandas as pd
from fastparquet import write

from google_flights import create_filter, get_flights_from_filter, FlightData, Passengers, TFSData, DecodedResult
from itertools import product, chain

import sqlite3

from regions import construct_routes


def collect_fligh_data(
        filter: TFSData,
        max_exceptions: int = 5,) -> Optional[DecodedResult]: 
    """
    Collect flight data from the given filter.

    Args:
        filter (TFSData): Filter criteria for flights.
        max_exceptions (int, optional): Maximum number of exceptions allowed. Defaults to 5.
    Returns:
        DecodedResult: parsed flight data.
    """
    attempts = 0
    while attempts < max_exceptions:
        try: 
            data = get_flights_from_filter(filter, data_source='js', mode='common')
            return data
        except Exception as e:
            logging.error(f"Error collecting flight data: {e}")
            attempts += 1
            sleep(2)

            if attempts >= max_exceptions:
                logging.error("Max exceptions reached. Using playwright")
                try: 
                    data = get_flights_from_filter(filter, data_source='playwright', mode='common')
                    return data
                except Exception as e:
                    logging.error(f"Error collecting flight data with playwright: {e}")
                    break

            continue
    
def get_datetime(date, time) -> datetime.datetime:
    """
    Deal with date and time format issues (example: [10], [Null, 20]).
    
    Returns:
        str: Converted datetime string.
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



def safe_get(value, default=None):
    try:
        if value is None or value == "" or value == "None" or value == "unknown":
            return default
        else: 
            return value
    except Exception:
        return default

def scrape_flight_data(
        data,
        today: datetime.date, 
        metadata: Dict[str, str],
    ):
    """
    Scrape flight data from the given data.
    """

    # Data extraction
    itin_records = []
    leg_records = []
    price_records = []
    if metadata is None or any(value is None for value in metadata.values()):
        metadata = {"region": {"unknown", "unknown"}, "time_window": {"midday"}}
    
    # Validate and combine best and other flight itineraries
    if not data or (not data.best and not data.other):
        raise ValueError("No flight data found")

    if data.best is not None:
        flight_Itinerarys = chain(data.best, data.other[:3])
    else:
        flight_Itinerarys = data.other[:3]

    for flight_Itinerary in flight_Itinerarys:

        if flight_Itinerary is None:
            logging.error("No flight_itinerary is found")
            continue
        
        # Extracting itinerary data
        departure_airport = safe_get(flight_Itinerary.departure_airport, default=None)
        arrival_airport = safe_get(flight_Itinerary.arrival_airport, default=None)
        
        try: 
            # Extracting date and time
            departure_datetime = get_datetime(flight_Itinerary.departure_date, flight_Itinerary.departure_time)
            arrival_datetime = get_datetime(flight_Itinerary.arrival_date, flight_Itinerary.arrival_time)
        except Exception as e:
            logging.error(f"Error extracting date/time: {e}")
            departure_datetime = None
            arrival_datetime = None


        flights = safe_get(flight_Itinerary.itinerary_summary.flights, [])

        itin_id = f"{flights}-{departure_datetime.isoformat()}-{departure_airport}-{arrival_airport}"
        total_emissions = 0
        trip_type = metadata.get("trip")
        seat_type = metadata.get("seat_type")
        region_from = metadata.get("region")[0]
        region_to = metadata.get("region")[1]

        # Extracting leg data
        for idx, f in enumerate(flight_Itinerary.flights):
            airline_code = safe_get(f.airline, default=None)
            flight_number = safe_get(f.flight_number, default=None)
            leg_id  = f"{airline_code}{flight_number}-{get_datetime(f.departure_date, f.departure_time).isoformat()}"
            total_emissions += safe_get(f.emissions, 20000)
            

            # Extracting features
            features = safe_get(f.features, {})
            feature_data = {
                key: 1 if features.get(key) == 'included' else 0
                for key in ["in_seat_power_usb", "in_seat_power", "usb_outlet", "on_demand_video", "streaming_media"]
            }
            wifi = safe_get(features.get("wifi"), default='0')
            feature_data["wifi"] = 1 if wifi == 'for free' else 2 if wifi == 'for fee' else 0
            leg_records.append({
                    "leg_id": leg_id,
                    "itinerary_id": itin_id,
                    "airline_code": airline_code,  # Handle missing airline code
                    "flight_number": flight_number,
                    "airline_name": safe_get(f.airline_name),
                    "operator": safe_get(f.operator),
                    "aircraft": safe_get(f.aircraft),
                    "src": safe_get(f.departure_airport),
                    "dst": safe_get(f.arrival_airport),
                    "departure_date": safe_get(datetime.date(*f.departure_date)).isoformat(),
                    "departure_datetime": get_datetime(f.departure_date, f.departure_time).isoformat(),
                    "arrival_datetime": get_datetime(f.arrival_date, f.arrival_time).isoformat(),
                    "travel_time": safe_get(f.travel_time),
                    "seat_pitch_short": safe_get(f.seat_pitch_short)[:-3] if safe_get(f.seat_pitch_short) is not None else None,
                    "seat_pitch_type": safe_get(f.seat_type),
                    "emissions": safe_get(f.emissions),
                    "in_seat_power_usb": feature_data.get("in_seat_power_usb"),
                    "in_seat_power_ac": feature_data.get("in_seat_power"),
                    "usb_outlet": feature_data.get("usb_outlet"),
                    "on_demand_media": feature_data.get("on_demand_video"),
                    "streaming_media": feature_data.get("streaming_media"),
                    "wifi": feature_data.get("wifi"),
                })
        price_records.append({
                "itinerary_id": itin_id,
                "price_datetime": datetime.datetime.now().isoformat(),
                "days_to_departure": (departure_datetime - datetime.datetime.now()).days if departure_datetime else None,
                "day_of_week": today.strftime("%A"),
                "time_window": metadata.get("time_window"),
                "price": safe_get(flight_Itinerary.itinerary_summary.price),
        })
        itin_records.append({
                    "itinerary_id": itin_id,
                    "flights_code": flights,  # Use None if missing
                    "airline_list": ', '.join(safe_get(flight_Itinerary.airline_names, [])),
                    "src": departure_airport,
                    "dst": arrival_airport,
                    "region_from": region_from,
                    "region_to": region_to,
                    "departure_date": safe_get(datetime.date(*flight_Itinerary.departure_date).isoformat(), default=None),
                    "departure_datetime": departure_datetime.isoformat(),
                    "arrival_datetime": arrival_datetime.isoformat(),
                    "travel_time": safe_get(flight_Itinerary.travel_time),
                    "layover_time": flight_Itinerary.layovers[0].minutes if flight_Itinerary.layovers is not None else 0,
                    "seat_type": seat_type,
                    "total_emissions": total_emissions,
                    "is_best": flight_Itinerary not in data.other,
                })
    return itin_records, leg_records, price_records
        


def scrape_one(
         metadata,
        route: Tuple[List[str], List[str]],
        departure_date: str,
        airlines: Optional[List[str]] = [],
    )-> Tuple[List[Dict], List[Dict], List[Dict]]:
    """
    Scrape flight data for a single route and date.
        
        
    Args:
        route (Tuple[List[str], List[str]]): Tuple containing departure and arrival airports.
        departure_date (str): Departure date in YYYY-MM-DD format.
        airlines (Optional[List[str]], optional): List of airlines to filter by. Defaults to [] (all airlines).
        metadata (Dict[str], optional): Metadata for the flight data. Defaults to None."""

    # Create filter for flights
    filt = create_filter(
        flight_data = [FlightData(
            airlines=[],
            date=departure_date,  # Date of departure
            from_airport=route[0],  # Departure airport
            to_airport=route[1],  # Arrival airports
        )],
        trip=metadata['trip_type'],  # Trip type
        passengers=metadata['passengers'],  # Passengers
        seat=metadata['seat_type'],  # Seat type
        max_stops=metadata['max_stops'],  # Maximum number of stops
    )

    data = collect_fligh_data(filt, max_exceptions=5)

    itin_records, leg_records, price_records = scrape_flight_data(
        data, 
        datetime.date.today(), 
        metadata)

    return itin_records, leg_records, price_records


def runner_collect_flight_data(max_stops: int, airlines: Optional[List[str]] = [], window: Optional[str] = None):
    """
    Collect flight data for multiple routes and dates.
        
    Args:
        window (Optional[str]): Time window for the flight data.

    """
    all_itin_records = []
    all_leg_records = []
    all_price_records = []

    logger = logging.getLogger(__name__)
    today = datetime.datetime.today()

    if window is None:
        now = datetime.datetime.now()
        if now.hour < 11:
            window = "morning"
        elif now.hour < 14:
            window = "midday"
        elif now.hour < 17:
            window = "afternoon"
        else:
            window = "evening"

    logging.info(f"Collecting flight data for {window}")
        
    offsets = (
        list(range(1, 8, 1)) +        # daily first week
        list(range(8, 31, 3)) +       # every 3 days next 3 weeks
        list(range(31, 91, 7))        # weekly up to 90 days
    )

    
    for offset in offsets:
        routes = construct_routes()
        departure_date = (today + datetime.timedelta(days=offset)).strftime("%Y-%m-%d")
        logging.info(f"Departure date: {departure_date}")

        for regions, src, dst in routes:

            if src == dst:
                continue

            metadata = {
                "trip_type": "one-way",
                "passengers": Passengers(adults=1, children=0, infants_in_seat=0, infants_on_lap=0),
                "seat_type": "economy",
                "max_stops": max_stops,
                "region": regions,
                "time_window": window,
            }

            try:
                itin_records, leg_records, price_records = scrape_one(
                    route=(src, dst),
                    departure_date=departure_date,
                    airlines=airlines,
                    metadata=metadata,
                )
                

                # Collect the records in lists
                all_itin_records.extend(itin_records)
                all_leg_records.extend(leg_records)
                all_price_records.extend(price_records)

            except Exception as e:
                logging.error(f"Error collecting flight data: {e}")
                continue # for now, just break the loop
    
        logging.info(f"Flight data collected for {departure_date}")
    
    all_itin_records = pd.DataFrame(all_itin_records)
    all_leg_records = pd.DataFrame(all_leg_records)
    all_price_records = pd.DataFrame(all_price_records)

    # Remove duplicates
    all_itin_records = all_itin_records.drop_duplicates(subset=["itinerary_id"], keep="last")
    all_leg_records = all_leg_records.drop_duplicates(subset=["leg_id"], keep="last")
    all_price_records = all_price_records.drop_duplicates(subset=["itinerary_id"], keep="last")

    # Convert date and time columns to appropriate formats
    all_itin_records['departure_datetime'] = pd.to_datetime(all_itin_records['departure_datetime'], errors='coerce')
    all_itin_records['arrival_datetime'] = pd.to_datetime(all_itin_records['arrival_datetime'], errors='coerce')
    all_leg_records['departure_datetime'] = pd.to_datetime(all_leg_records['departure_datetime'], errors='coerce')
    all_leg_records['arrival_datetime'] = pd.to_datetime(all_leg_records['arrival_datetime'], errors='coerce')
    all_price_records['price_datetime'] = pd.to_datetime(all_price_records['price_datetime'], errors='coerce')

    write(
        'itineraries',              # directory for hive scheme
        all_itin_records,
        compression='SNAPPY',
        file_scheme='hive',
        partition_on=['departure_date', 'flights_code'],
        append='overwrite',
        write_index=False
    )
    write(
        'legs', 
        all_leg_records, 
        compression='SNAPPY', 
        file_scheme='hive',
        partition_on=['departure_date', 'flight_number'],
        append='overwrite',
        write_index=False
    )
    write('prices.parquet', all_price_records, compression='SNAPPY', append=False, has_nulls=True)


    del all_itin_records, all_leg_records, all_price_records
    gc.collect()
    logging.info("Flight data collection completed.")


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


def main():
    args = parse_args()
    setup_logging()
    runner_collect_flight_data(args.max_stops, args.airlines, args.window)


if __name__ == "__main__":
    main()