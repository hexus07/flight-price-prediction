from bs4 import BeautifulSoup
import pandas as pd
import requests
import itertools
import numpy as np
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='demand_scraping/demand_scraper.log'
)
logger = logging.getLogger(__name__)


codes_df = pd.read_csv('demand_scraping/iata-icao.csv').dropna()
ICAO_dict = codes_df.set_index('iata')['icao'].to_dict()

# Get only first word of the 'Ciudad / Location' column
codes_df['Ciudad / Location'] = codes_df['Ciudad / Location'].str.split(',').str[0]
CITY_dict = codes_df.set_index('iata')['Ciudad / Location'].to_dict()

with open('demand_scraping/proxies.txt', 'r') as f:
    proxies = [line.strip() for line in f if line.strip()]

# Create a cycle iterator for proxies
PROXY_CYCLE = itertools.cycle(proxies)


def get_response(url: str, max_retries: int = 3, backoff_factor: float = 2.0):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    attempt = 0
    while attempt < max_retries:
        proxy = next(PROXY_CYCLE)
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
                #time.sleep(backoff_factor ** attempt)  # Exponential backoff
        except requests.RequestException as e:
            logger.error(f"Request error with proxy {proxy}: {e}")
            attempt += 1
            time.sleep(backoff_factor ** attempt)
    logger.error(f"Failed to fetch {url} after {max_retries} attempts")
    return None

def parse_response(response: requests.Response):
    soup = BeautifulSoup(response.text, 'html.parser')
    info_blocks = soup.find_all('div', class_='text-center')
    
    dict_demand = {}
    if not info_blocks:
        logger.warning("No information blocks found in the response.")
        return dict_demand
    
    for block in info_blocks:
        label = block.find('div', class_='text-slate-600')
        if label:
                label_text = label.get_text(strip=True).upper()
                value_div = block.find('div', class_='text-slate-800')
                if label_text and value_div:
                    value_text = value_div.get_text(strip=True)
                    dict_demand[label_text] = value_text
    logger.info("Successfully parsed the response.")
    return dict_demand



def get_flight_demand(airline: str, src: str, dst: str, flight_number: str):
    """
    Fetches flight demand data for a specific route and date.
    
    :param airline: Airline name
    :param src: Source IATA code
    :param dst: Destination IATA code
    :param flight_number: Flight number
    :param departure_date: Departure date in 'YYYY-MM-DD' format
    :return: Dictionary with flight demand data
    """

    src_city = CITY_dict.get(src.upper()).replace(' ', '+')
    src_icao = ICAO_dict.get(src.upper())
    dst_city = CITY_dict.get(dst.upper()).replace(' ', '+')

    print(f"Fetching data for {airline} flight {flight_number} from {src_city} to {dst_city}")
    url = f'https://www.flightera.net/en/flight/{airline}-{src_city}{dst_city}/{flight_number}'
    response = get_response(url)

    if response is None:
        logger.error(f"Failed to fetch data for {airline} flight {flight_number} from {src} to {dst}")
        return {}
    
    return parse_response(response)





test = get_flight_demand('Ryanair', 'RIX', 'TRF', 'FR2869')
print(test)


# How maany of routes was for each of flight_number
routes_per_flight = merged_df2.groupby('flight_number')[['src', 'dst']].nunique()

# save only this which had diffrernt routes
multi_route_flights = routes_per_flight[(routes_per_flight['src'] > 1) | (routes_per_flight['dst'] > 1)]

print(f"Number of flight_numbers used for multiple routes: {multi_route_flights.shape[0]}")

# Check number of unique routes and flight numbers
unique_routes = merged_df2[['src', 'dst']].drop_duplicates()
flight_numbers = merged_df2.drop_duplicates(subset=['flight_number'], keep='first')

print(f"Unique flight numbers: {flight_numbers.shape[0]} for {unique_routes.shape[0]} routes")

flight_numbers['flight_number'] =flight_numbers['flight_number'].astype(str).str.strip()

flight_numbers['flight_number'] =  flight_numbers['airline_code'] + flight_numbers['flight_number']
unique_dst = flight_numbers[['dst']].drop_duplicates()
unique_src = flight_numbers[['src']].drop_duplicates()



codes_df = pd.read_csv('demand_scraping/iata-icao.csv').dropna()
ICAO_dict = codes_df.set_index('iata')['icao'].to_dict()

# Get only first word of the 'Ciudad / Location' column
codes_df['Ciudad / Location'] = codes_df['Ciudad / Location'].str.split(',').str[0]
CITY_dict = codes_df.set_index('iata')['Ciudad / Location'].to_dict()

# check if all src and dst in CITY_dict
missing_src = set(flight_numbers['src']) - set(CITY_dict.keys())
missing_dst = set(flight_numbers['dst']) - set(CITY_dict.keys())
missing_cities = missing_src.union(missing_dst)

if missing_cities:
    print(f"Missing src codes: {missing_cities}")

print(flight_numbers.head())





from demand_scraping.flight_demand2 import get_flight_demand
def scrape(flight_numbers):
    result = pd.DataFrame(columns=['flight_number','frequency', 'distance', 'flights/week', 'punctuality'])
    missed_flight_numbers = []
    for index, row in flight_numbers.iterrows():
        print(f"Processing flight number: {row['flight_number']}")
        try:
            flight_demand = get_flight_demand(airline=row['airline_name'], src = row['src'], dst = row['dst'], flight_number=row['flight_number'])
            result.loc[len(result)] = {
                'flight_number': row['flight_number'],
                'frequency': flight_demand.get('FREQUENCY', None),
                'distance': flight_demand.get('DISTANCE', None),
                'flights/week': flight_demand.get('FLIGHTS/WEEK', None),
                'punctuality': flight_demand.get('PUNCTUALITY', None)
            }
        except Exception as e:
            print(f"Error processing flight number {row['flight_number']}: {e}")
            missed_flight_numbers.append(row['flight_number'])
            continue
        print("----------------------")
    return result, missed_flight_numbers