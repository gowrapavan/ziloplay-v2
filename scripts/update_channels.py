import json
import time
from pathlib import Path
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


API_BASE = "https://api.bingr.one/api"
CHANNELS_ENDPOINT = f"{API_BASE}/iptv/channels"

LIMIT = 200
OUTPUT_FILE = Path("data/channels.json")


def create_session():
    session = requests.Session()

    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )

    adapter = HTTPAdapter(max_retries=retry)

    session.mount("https://", adapter)
    session.mount("http://", adapter)

    session.headers.update({
        "User-Agent": "Bingr-Channel-Updater/1.0",
        "Accept": "application/json",
    })

    return session


def extract_channels(data):
    """
    Handle common API response structures.
    """

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ("channels", "items", "data"):
            value = data.get(key)

            if isinstance(value, list):
                return value

    return []


def get_all_channels(session):
    all_channels = []
    offset = 0

    while True:
        print(f"Fetching channels: offset={offset}")

        response = session.get(
            CHANNELS_ENDPOINT,
            params={
                "limit": LIMIT,
                "offset": offset,
            },
            timeout=30,
        )

        response.raise_for_status()

        data = response.json()
        channels = extract_channels(data)

        if not channels:
            break

        all_channels.extend(channels)

        print(
            f"Received {len(channels)} channels "
            f"(total: {len(all_channels)})"
        )

        if len(channels) < LIMIT:
            break

        offset += LIMIT

        # Be polite to the API
        time.sleep(0.25)

    return all_channels


def get_stream(session, channel_id):
    endpoint = (
        f"{API_BASE}/iptv/stream/"
        f"{quote(str(channel_id), safe='')}"
    )

    response = session.get(
        endpoint,
        timeout=30,
    )

    if response.status_code != 200:
        print(
            f"  Stream request failed: "
            f"HTTP {response.status_code}"
        )
        return None

    return response.json()


def update_stream_information(session, channels):
    successful = 0
    failed = 0

    for index, channel in enumerate(channels, 1):

        channel_id = channel.get("id")

        if not channel_id:
            print(f"[{index}/{len(channels)}] Missing channel ID")
            failed += 1
            continue

        name = channel.get("name", channel_id)

        print(
            f"[{index}/{len(channels)}] "
            f"{name} ({channel_id})"
        )

        try:
            stream = get_stream(session, channel_id)

            if stream:
                # Preserve ALL fields returned by /channels
                # and add/update stream information.
                channel["streamUrl"] = stream.get("streamUrl")
                channel["quality"] = stream.get("quality")

                # Keep additional stream metadata if available.
                if stream.get("name"):
                    channel["streamName"] = stream["name"]

                if stream.get("logo"):
                    channel["streamLogo"] = stream["logo"]

                successful += 1
            else:
                channel["streamUrl"] = None
                failed += 1

        except requests.RequestException as exc:
            print(f"  Request error: {exc}")
            channel["streamUrl"] = None
            failed += 1

        except Exception as exc:
            print(f"  Error: {exc}")
            channel["streamUrl"] = None
            failed += 1

        time.sleep(0.1)

    return successful, failed


def save_channels(channels):
    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # Sort by channel name for stable output.
    channels.sort(
        key=lambda x: (
            str(x.get("name") or "").lower(),
            str(x.get("id") or "").lower(),
        )
    )

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            channels,
            file,
            ensure_ascii=False,
            indent=2,
        )

        file.write("\n")


def main():
    print("=" * 60)
    print("Bingr IPTV Channel Updater")
    print("=" * 60)

    session = create_session()

    # Get all available channels.
    channels = get_all_channels(session)

    print()
    print(f"Total channels found: {len(channels)}")

    if not channels:
        raise RuntimeError(
            "API returned zero channels. "
            "Refusing to overwrite existing data."
        )

    # Get stream URL and additional metadata.
    successful, failed = update_stream_information(
        session,
        channels,
    )

    # Save.
    save_channels(channels)

    print()
    print("=" * 60)
    print("Update complete")
    print("=" * 60)
    print(f"Channels:       {len(channels)}")
    print(f"Streams found:  {successful}")
    print(f"Streams failed: {failed}")
    print(f"Output:         {OUTPUT_FILE}")


if __name__ == "__main__":
    main()