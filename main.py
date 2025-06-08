#!/usr/bin/env python3
"""
YouTube Bulk Subscribe Script
Automatically subscribe to multiple YouTube channels using the YouTube Data API v3
"""

import csv
import json
import os
import pickle
import time
from typing import List
from urllib.parse import urlparse

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# YouTube API settings
SCOPES = ["https://www.googleapis.com/auth/youtube"]
API_SERVICE_NAME = "youtube"
API_VERSION = "v3"


class YouTubeBulkSubscriber:
    def __init__(self, credentials_file="credentials.json"):
        self.credentials_file = credentials_file
        self.token_file = "token.pickle"
        self.youtube = None
        self.authenticate()

    def authenticate(self):
        """Handle OAuth2 authentication for YouTube API"""
        creds = None

        # Load existing token if available
        if os.path.exists(self.token_file):
            with open(self.token_file, "rb") as token:
                creds = pickle.load(token)

        # If no valid credentials, get new ones
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(self.credentials_file):
                    raise FileNotFoundError(
                        f"Credentials file '{self.credentials_file}' not found. "
                        "Download it from Google Cloud Console."
                    )

                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_file, SCOPES
                )
                creds = flow.run_local_server(port=0)

            # Save credentials for next run
            with open(self.token_file, "wb") as token:
                pickle.dump(creds, token)

        # Build YouTube service
        self.youtube = build(API_SERVICE_NAME, API_VERSION, credentials=creds)
        print("✅ Authentication successful!")

    def extract_channel_id(self, url: str) -> str:
        """Extract channel ID from various YouTube URL formats"""
        parsed_url = urlparse(url)

        # Handle different URL formats
        if "channel/" in url:
            # https://www.youtube.com/channel/UC...
            return url.split("channel/")[-1].split("?")[0]
        elif "c/" in url or "@" in url:
            # https://www.youtube.com/c/channelname or https://www.youtube.com/@username
            # Need to resolve custom URL to channel ID
            return self.resolve_custom_url(url)
        elif "user/" in url:
            # https://www.youtube.com/user/username
            username = url.split("user/")[-1].split("?")[0]
            return self.get_channel_id_by_username(username)
        else:
            raise ValueError(f"Unable to parse channel URL: {url}")

    def resolve_custom_url(self, url: str) -> str:
        """Resolve custom URL or @username to channel ID"""
        try:
            # Extract the custom name/username
            if "@" in url:
                handle = url.split("@")[-1].split("?")[0]
                search_query = f"@{handle}"
            else:
                custom_name = url.split("c/")[-1].split("?")[0]
                search_query = custom_name

            # Search for the channel
            search_response = (
                self.youtube.search()
                .list(q=search_query, type="channel", part="id", maxResults=1)
                .execute()
            )

            if search_response["items"]:
                return search_response["items"][0]["id"]["channelId"]
            else:
                raise ValueError(f"Could not find channel for URL: {url}")

        except HttpError as e:
            print(f"❌ Error resolving custom URL {url}: {e}")
            raise

    def get_channel_id_by_username(self, username: str) -> str:
        """Get channel ID from username"""
        try:
            channels_response = (
                self.youtube.channels().list(forUsername=username, part="id").execute()
            )

            if channels_response["items"]:
                return channels_response["items"][0]["id"]
            else:
                raise ValueError(f"Channel not found for username: {username}")

        except HttpError as e:
            print(f"❌ Error getting channel ID for username {username}: {e}")
            raise

    def subscribe_to_channel(self, channel_id: str) -> bool:
        """Subscribe to a single channel"""
        try:
            # Check if already subscribed
            try:
                existing_sub = (
                    self.youtube.subscriptions()
                    .list(part="id", forChannelId=channel_id, mine=True)
                    .execute()
                )

                if existing_sub["items"]:
                    print(f"⚠️  Already subscribed to channel: {channel_id}")
                    return True
            except HttpError:
                pass  # Not subscribed, continue

            # Subscribe to the channel
            subscription_response = (
                self.youtube.subscriptions()
                .insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "resourceId": {
                                "kind": "youtube#channel",
                                "channelId": channel_id,
                            }
                        }
                    },
                )
                .execute()
            )

            print(f"✅ Successfully subscribed to channel: {channel_id}")
            return True

        except HttpError as e:
            error_details = json.loads(e.content.decode("utf-8"))
            error_reason = (
                error_details.get("error", {})
                .get("errors", [{}])[0]
                .get("reason", "unknown")
            )

            if error_reason == "subscriptionDuplicate":
                print(f"⚠️  Already subscribed to channel: {channel_id}")
                return True
            else:
                print(f"❌ Failed to subscribe to {channel_id}: {e}")
                return False

    def bulk_subscribe(self, channel_urls: List[str], delay: float = 1.0):
        """Subscribe to multiple channels with rate limiting"""
        print(f"🚀 Starting bulk subscription to {len(channel_urls)} channels...")

        successful = 0
        failed = 0

        for i, url in enumerate(channel_urls, 1):
            print(f"\n[{i}/{len(channel_urls)}] Processing: {url}")

            try:
                channel_id = self.extract_channel_id(url.strip())

                if self.subscribe_to_channel(channel_id):
                    successful += 1
                else:
                    failed += 1

            except Exception as e:
                print(f"❌ Error processing {url}: {e}")
                failed += 1

            # Rate limiting - be respectful to YouTube's API
            if i < len(channel_urls):  # Don't delay after the last one
                time.sleep(delay)

        print("\n📊 Summary:")
        print(f"✅ Successful subscriptions: {successful}")
        print(f"❌ Failed subscriptions: {failed}")
        print(f"📈 Success rate: {successful / (successful + failed) * 100:.1f}%")


def load_urls_from_csv(csv_file: str) -> List[str]:
    """Load YouTube channel URLs from the second column of a CSV file"""
    channel_urls = []

    try:
        with open(csv_file, "r", encoding="utf-8", newline="") as file:
            csv_reader = csv.reader(file)

            # Skip header row if it exists (optional)
            try:
                first_row = next(csv_reader)
                # Check if first row looks like a header
                if not any(
                    url_indicator in str(first_row[1]).lower()
                    for url_indicator in ["youtube.com", "youtu.be", "http"]
                ):
                    print(f"ℹ️  Skipping header row: {first_row}")
                else:
                    # First row contains a URL, add it back
                    if len(first_row) >= 2 and first_row[1].strip():
                        channel_urls.append(first_row[1].strip())
            except (StopIteration, IndexError):
                print("❌ CSV file appears to be empty or malformed")
                return []

            # Read remaining rows
            for row_num, row in enumerate(csv_reader, start=2):
                try:
                    if (
                        len(row) >= 2 and row[1].strip()
                    ):  # Check if second column exists and is not empty
                        url = row[1].strip()
                        if url:  # Only add non-empty URLs
                            channel_urls.append(url)
                except IndexError:
                    print(f"⚠️  Row {row_num} doesn't have a second column, skipping")
                    continue

        print(f"📂 Loaded {len(channel_urls)} URLs from {csv_file}")
        return channel_urls

    except FileNotFoundError:
        print(f"❌ CSV file '{csv_file}' not found")
        return []
    except Exception as e:
        print(f"❌ Error reading CSV file: {e}")
        return []


def main():
    """Main function to run the bulk subscriber"""

    csv_filename = "subscriptions.csv"  # Default CSV filename

    # Try to load URLs from CSV file
    channel_urls = load_urls_from_csv(csv_filename)

    if not channel_urls:
        print(
            f"\n📋 No URLs found in {csv_filename}. Please create a CSV file with this format:"
        )
        print("Column1,YouTubeURL")
        print("Channel Name,https://www.youtube.com/channel/UC_x5XG1OV2P6uZZ5FSM9Ttw")
        print("Another Channel,https://www.youtube.com/@3Blue1Brown")
        print("Tech Channel,https://www.youtube.com/c/TechLead")
        return

    try:
        subscriber = YouTubeBulkSubscriber("credentials.json")
        subscriber.bulk_subscribe(
            channel_urls, delay=1.0
        )  # 1 second delay between requests

    except FileNotFoundError as e:
        print(f"❌ {e}")
        print("\n📋 Setup Instructions:")
        print("1. Go to Google Cloud Console (https://console.cloud.google.com/)")
        print("2. Create a new project or select existing one")
        print("3. Enable YouTube Data API v3")
        print("4. Create OAuth2 credentials (Desktop application)")
        print("5. Download the credentials JSON file as 'credentials.json'")
        print("6. Place it in the same directory as this script")

    except Exception as e:
        print(f"❌ Unexpected error: {e}")


if __name__ == "__main__":
    main()
