import argparse
import csv
from datetime import datetime, timedelta
import os
import requests


def load_config(config_path="config.txt"):
  config = {}
  if not os.path.exists(config_path):
    raise FileNotFoundError(f"Config file '{config_path}' not found.")
  with open(config_path, "r") as f:
    for line in f:
      line = line.strip()
      if line and not line.startswith("#"):
        key, val = line.split("=", 1)
        config[key.strip()] = val.strip()
  return config


def load_airports(input_path):
  if not os.path.exists(input_path):
    raise FileNotFoundError(f"Input file '{input_path}' not found.")
  airports = []
  with open(input_path, "r") as f:
    for line in f:
      code = line.strip()
      if code:
        airports.append(code)
  return airports


def fetch_departures_slot(
    airport, from_str, to_str, api_url_template, api_key, api_host
):
  """Fetches departures for a single 12-hour window, supporting both Direct and

  RapidAPI routing automatically based on config.
  """
  url = api_url_template.format(
      airport=airport, from_local=from_str, to_local=to_str
  )

  params = {"direction": "Departure", "withLeg": "true", "withCancelled": "true"}

  # Determine authentication headers based on whether API_HOST is provided
  if api_host:
    headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": api_host}
  else:
    headers = {"X-API-Key": api_key}

  response = requests.get(url, headers=headers, params=params)
  if response.status_code != 200:
    print(
        f"Error fetching {airport} ({from_str} to {to_str}):"
        f" {response.status_code} - {response.text}"
    )
    return []

  data = response.json()
  return data.get("departures", [])


def fetch_full_day_departures(
    airport, date_str, api_url_template, api_key, api_host
):
  """AeroDataBox limits queries to 12-hour windows.

  Splits the day into 00:00-11:59 and 12:00-23:59.
  """
  slot1_from = f"{date_str}T00:00"
  slot1_to = f"{date_str}T11:59"

  slot2_from = f"{date_str}T12:00"
  slot2_to = f"{date_str}T23:59"

  flights_slot1 = fetch_departures_slot(
      airport, slot1_from, slot1_to, api_url_template, api_key, api_host
  )
  flights_slot2 = fetch_departures_slot(
      airport, slot2_from, slot2_to, api_url_template, api_key, api_host
  )

  return flights_slot1 + flights_slot2


def main():
  parser = argparse.ArgumentParser(
      description="Fetch daily flight departures from AeroDataBox API."
  )
  parser.add_argument(
      "--date",
      type=str,
      default=datetime.now().strftime("%Y-%m-%d"),
      help="Date in YYYY-MM-DD format (defaults to today)",
  )
  parser.add_argument(
      "--config", type=str, default="config.txt", help="Path to config file"
  )
  parser.add_argument(
      "--output-dir", type=str, default=".", help="Directory to save CSV output"
  )

  args = parser.parse_args()

  try:
    config = load_config(args.config)
    input_path = config.get("INPUT_FILE", "input.txt")
    airports = load_airports(input_path)
  except Exception as e:
    print(f"Configuration error: {e}")
    return

  api_url_template = config.get("API_URL")
  api_key = config.get("API_KEY")
  api_host = config.get(
      "API_HOST"
  )  # Optional: Will be None if commented out with #

  if not api_url_template or not api_key:
    print("Error: API_URL and API_KEY must be defined in config.txt")
    return

  all_flights = []

  for airport in airports:
    print(f"Fetching departures for {airport} on {args.date}...")
    flights = fetch_full_day_departures(
        airport, args.date, api_url_template, api_key, api_host
    )

    for flight in flights:
      airline = flight.get("airline", {})
      dest = flight.get("movement", {}).get("airport", {})
      scheduled_time = (
          flight.get("movement", {}).get("scheduledTime", {}).get("local")
      )
      revised_time = (
          flight.get("movement", {}).get("revisedTime", {}).get("local")
      )

      row = {
          "airport": airport,
          "date": args.date,
          "flight_number": flight.get("number"),
          "callsign": flight.get("callSign"),
          "airline": airline.get("name") if isinstance(airline, dict) else "",
          "destination_iata": dest.get("iata") if isinstance(dest, dict) else "",
          "destination_name": dest.get("name") if isinstance(dest, dict) else "",
          "scheduled_time": scheduled_time,
          "revised_time": revised_time,
          "status": flight.get("status"),
      }
      all_flights.append(row)

  if not all_flights:
    print("No flight data retrieved.")
    return

  os.makedirs(args.output_dir, exist_ok=True)
  output_filename = os.path.join(args.output_dir, f"flights_{args.date}.csv")

  fieldnames = [
      "airport",
      "date",
      "flight_number",
      "callsign",
      "airline",
      "destination_iata",
      "destination_name",
      "scheduled_time",
      "revised_time",
      "status",
  ]

  with open(
      output_filename, mode="w", newline="", encoding="utf-8"
  ) as csv_file:
    writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
    writer.writeheader()
    for flight_row in all_flights:
      writer.writerow(flight_row)

  print(
      f"Successfully saved {len(all_flights)} flights to {output_filename}"
  )


if __name__ == "__main__":
  main()
