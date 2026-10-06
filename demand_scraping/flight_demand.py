from fastapi import requests as fastapi_requests  # Avoid naming conflict
import pandas as pd
import sqlite3
import requests
import itertools
import numpy as np
from selectolax.lexbor import LexborHTMLParser, LexborNode
import time
import logging
from typing import Optional, Dict, List

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='demand_scraping/demand_scraper.log'
)
logger = logging.getLogger(__name__)

# Load the IATA-ICAO codes mapping
icao_codes_df = pd.read_csv('demand_scraping/iata-icao-coordinates.csv')
icao_dict = icao_codes_df.set_index('iata')['icao'].to_dict()
coordinates_dict = icao_codes_df.set_index('iata')[['latitude', 'longitude']].to_dict(orient='index')

# Read proxy list
with open('demand_scraping/proxies.txt', 'r') as f:
    PROXIES_LIST = [line.strip() for line in f if line.strip()]

# Create a cycle iterator for proxies
proxy_cycle = itertools.cycle(PROXIES_LIST)

class FlightDemand:
    def __init__(self, total_flights: int, num_airlines: int, distance_km: int, 
                 flights_per_airline: Dict[str, int], delays_per_flight: Dict[str, int]):
        self.total_flights = total_flights
        self.num_airlines = num_airlines
        self.distance_km = distance_km
        self.flights_per_airline = flights_per_airline
        self.delays_per_flight = delays_per_flight

    def get_flights_per_airline(self, airline: Optional[str] = None) -> dict[str, int] | int:
        if airline:
            return self.flights_per_airline.get(airline, 0)
        return self.flights_per_airline

    def __repr__(self) -> str:
        return (f"FlightDemand(total_flights={self.total_flights}, "
                f"num_airlines={self.num_airlines}, "
                f"distance_km={self.distance_km}, "
                f"flights_per_airline={self.flights_per_airline}, "
                f"delays_per_flight={self.delays_per_flight})")

def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371  # Earth radius in km
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = np.sin(dlat/2)**2 + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dlon/2)**2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    return R * c

def adjusted_flight_distance(airport_from: str, airport_to: str) -> int:
    try:
        lat1, lon1 = coordinates_dict[airport_from]['latitude'], coordinates_dict[airport_from]['longitude']
        lat2, lon2 = coordinates_dict[airport_to]['latitude'], coordinates_dict[airport_to]['longitude']
        if any(x is None for x in [lat1, lon1, lat2, lon2]):
            raise ValueError(f"Coordinates for {airport_from} or {airport_to} not found.")
        return round(haversine_distance_km(lat1, lon1, lat2, lon2))
    except KeyError as e:
        logger.error(f"Airport not found in coordinates dictionary: {e}")
        raise ValueError(f"Airport {e} not found.")

def fetch_search(url: str, max_retries: int = 3, backoff_factor: float = 2.0) -> Optional[requests.Response]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    attempt = 0
    while attempt < max_retries:
        proxy = next(proxy_cycle)
        try:
            proxy_parts = proxy.split(':')
            if len(proxy_parts) != 4:
                logger.warning(f"Invalid proxy format: {proxy}")
                attempt += 1
                continue
            proxies = {
                "http": f"http://{proxy_parts[2]}:{proxy_parts[3]}@{proxy_parts[0]}:{proxy_parts[1]}/",
                "https": f"http://{proxy_parts[2]}:{proxy_parts[3]}@{proxy_parts[0]}:{proxy_parts[1]}/"
            }
            logger.info(f"Attempt {attempt + 1}/{max_retries} using proxy: {proxy}")
            response = requests.get(url, proxies=proxies, headers=headers, timeout=10)
            if response.status_code == 200:
                logger.info(f"Successfully fetched data from {url}")
                return response
            else:
                logger.warning(f"Failed to fetch data: {response.status_code} - {response.text}")
                attempt += 1
                time.sleep(backoff_factor ** attempt)  # Exponential backoff
        except requests.RequestException as e:
            logger.error(f"Request error with proxy {proxy}: {e}")
            attempt += 1
            time.sleep(backoff_factor ** attempt)
    logger.error(f"Failed to fetch {url} after {max_retries} attempts")
    return None

def parse_response(response: requests.Response) -> Optional[LexborNode]:
    try:
        parser = LexborHTMLParser(response.text)
        table = parser.css_first('table')
        if not table:
            logger.warning("No table found in response")
            return None
        return table
    except Exception as e:
        logger.error(f"Error parsing response: {e}")
        return None

def table_to_dataframe(table_node: LexborNode) -> pd.DataFrame:
    headers = [th.text(strip=True) for th in table_node.css('th')]
    n_cols = len(headers) if headers else None
    rows = []
    for tr in table_node.css('tr'):
        cells = [td.text(strip=True) for td in tr.css('td')]
        if n_cols is not None and cells:
            cells = cells[:n_cols]
            rows.append(cells)
    return pd.DataFrame(rows, columns=headers)

def process_data(df: pd.DataFrame) -> pd.DataFrame:
    processed_df = df.copy()
    processed_df['DURATION'] = processed_df['DURATION'].replace(['', 'None', 'NaN'], np.nan)
    processed_df.dropna(subset=['DATE / STATUS', 'Flight', 'FROM/ TO', 'DURATION'], inplace=True)

    processed_df[['weekday', 'date', 'month', 'time']] = processed_df['DATE / STATUS'].str.extract(
        r'(\w+),\s*(\d{2})\. (\w+)\d{2} \w+ (\d{2}:\d{2})', expand=False
    )
    processed_df['date'] = pd.to_datetime(
        processed_df['date'] + ' ' + processed_df['month'] + ' 2025', errors='coerce')
    processed_df[['flight_number']] = processed_df['Flight'].str.extract(r'([A-Z]{1,2}\d+)')
    processed_df['airline'] = processed_df['Flight'].str.extract(r'([A-Z][a-z]+(?: [A-Z][a-z]+)*)')
    processed_df['DELAY'] = processed_df['DURATION'].str.extract(r'((?:\d+h )?\d+min\s*(?:early|late)|on time)')

    def convert_delay_to_minutes(s: str) -> int:
        if s == 'on time':
            return 0
        delay = s.split(' ')
        time, status = delay[:-1], delay[-1]
        if len(time) == 1:
            minutes = int(time[0].replace('min', ''))
            return minutes if status == 'late' else -minutes
        elif len(time) == 2:
            hours = int(time[0].replace('h', ''))
            minutes = int(time[1].replace('min', ''))
            total_minutes = hours * 60 + minutes
            return total_minutes if status == 'late' else -total_minutes
        return 0

    processed_df['delay_minutes'] = processed_df['DELAY'].apply(convert_delay_to_minutes)
    processed_df = processed_df.dropna(subset=['date'])

    return processed_df[['flight_number', 'airline', 'FROM/ TO', 'TO', 'delay_minutes', 'date', 'time']]

def get_flights(airport_from: str, airport_to: str, date: str, max_attempts_per_day: int = 5) -> Optional[pd.DataFrame]:
    icao_from = icao_dict.get(airport_from)
    icao_to = icao_dict.get(airport_to)
    if not icao_from or not icao_to:
        logger.error(f"Invalid airport codes: {airport_from}, {airport_to}")
        return None

    latest_response_day = date
    latest_response_time = '00_00'
    result_df = pd.DataFrame()
    attempts = 0

    while pd.to_datetime(latest_response_day) == pd.to_datetime(date) and attempts < max_attempts_per_day:
        url = f"https://www.flightera.net/route/{icao_from}/{icao_to}/{date}%20%20{latest_response_time}"
        logger.info(f"Fetching data from: {url}")

        response = fetch_search(url)
        if not response:
            logger.warning(f"Failed to fetch data for {url}, trying next proxy")
            attempts += 1
            continue

        data = parse_response(response)
        if not data:
            logger.warning(f"Failed to parse response for {url}, trying next proxy")
            attempts += 1
            continue

        df = table_to_dataframe(data)
        if df.empty:
            logger.warning(f"No data extracted from table for {url}")
            attempts += 1
            continue

        processed_df = process_data(df)
        if processed_df.empty:
            logger.warning(f"No valid data after processing for {url}")
            attempts += 1
            continue

        processed_df.dropna(subset=['date'], inplace=True)
        result_df = pd.concat([result_df, processed_df], ignore_index=True)
        latest_response_day = processed_df['date'].iloc[-1].strftime('%Y-%m-%d')
        try:
            latest_response_time = pd.to_datetime(processed_df['time'].iloc[-1]).strftime('%H_%M')
        except ValueError:
            logger.error(f"Invalid time format in response for {url}, skipping time update")
        attempts = 0  # Reset attempts on successful fetch

    if result_df.empty:
        logger.error(f"No data retrieved for {airport_from} to {airport_to} on {date}")
        return None
    return result_df

def analyze_flight_demand(airport_from: str, airport_to: str, date: str) -> FlightDemand:
    logger.info(f"Analyzing flight demand for {airport_from} to {airport_to} on {date}")
    flights = get_flights(airport_from, airport_to, date)
    if flights is not None and not flights.empty:
        flights_today = flights[flights['date'] == date]
        if flights_today.empty:
            raise ValueError(f"No flights found for {date}")
        flights_per_airline = flights_today['airline'].value_counts().to_dict()
        num_airlines = flights_today['airline'].nunique()
        total_flights = flights_today.shape[0]
        distance = adjusted_flight_distance(airport_from, airport_to)
        delays_per_flight = flights_today[['flight_number', 'delay_minutes']].set_index('flight_number').to_dict()['delay_minutes']
        return FlightDemand(
            total_flights=total_flights,
            num_airlines=num_airlines,
            distance_km=distance,
            flights_per_airline=flights_per_airline,
            delays_per_flight=delays_per_flight
        )
    raise ValueError(f"No data found for the route {airport_from} to {airport_to} on {date}")


