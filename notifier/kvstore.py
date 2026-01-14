import requests
import json
import urllib.request
import time
import random
import logging

class VersionedKeyValue():
    
    def __init__(self, value, version, key = None):
        self.key = key
        self.value = value
        self.version = version

class Movie():
    
    def __init__(self, date, time, id):
        self.date = date
        self.time = time
        self.id = id

    def dict(self):
        return {
            'date': self.date,
            'time': self.time,
            'id': self.id
        }

class KVClient():

    def __init__(self, base_url):
        self.base_url = f"http://{base_url.rstrip('/')}"
    
    def get(self, key):
        logger = logging.getLogger(__name__)
        logger.info(f"Fetching key: {key}")
        try:
            response = requests.get(f"{self.base_url}/api/get", params={'id': key})
        except Exception as e:
            logger.info(f"Connection error while fetching key {key}: {e}")
            raise
        logger.info(f"GET {response.url} - Status: {response.status_code}")
        response.raise_for_status() # Automatically handles non-200 errors
        data = response.json()
        if data['value'] == None and data['version'] == 0:
            return None
        return VersionedKeyValue(**data)

    def put(self, vkv: VersionedKeyValue):
        logger = logging.getLogger(__name__)

        uri = f"{self.base_url}/api/put"
        
        # Convert the object to a dictionary, then to JSON bytes
        data = json.dumps({
            'key': vkv.key,
            'value': vkv.value,
            'version': vkv.version
        }).encode('utf-8')

        logger.info(f"PUT {uri} with data: {data}")
        
        req = urllib.request.Request(
            uri, 
            data=data, 
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        
        with urllib.request.urlopen(req) as response:
            if response.status != 200:
                raise ValueError(f"Server returned error: {response.status}")

    def list(self) -> list[VersionedKeyValue]:
        uri = f"{self.base_url}/api/list"
        
        with urllib.request.urlopen(uri) as response:
            if response.status != 200:
                return []
            
            raw_data = response.read()
            json_list = json.loads(raw_data.decode('utf-8'))
            
            # Map the JSON array back to a list of VersionedKeyValue objects
            return [
                VersionedKeyValue(key = item['key'], item = item['value'], version = item['version'])
                for item in json_list
            ]

    def reset(self):
        uri = f"{self.base_url}/api/reset"
        
        with urllib.request.urlopen(uri) as response:
            if response.status != 200:
                raise ValueError(f"Reset failed with status: {response.status}")
            
class MovieStore():
    
    def __init__(self, url: str):
        self.kv_client = KVClient(url)
        self.max_retries = 5

    def get_movie(self, movie_id):
        vkv = self.kv_client.get(movie_id)
        return vkv.value if vkv else None
    
    def put_movie(self, movie_id, movie_data):
        retries = 0
        while retries < self.max_retries:
            try:
                # 1. Fetch current state
                try:
                    existing = self.kv_client.get(movie_id)
                    version = existing.version + 1
                except Exception: 
                    # Assume 404/Not Found means version 1
                    version = 1
                
                # 2. Attempt the Write
                new_vkv = VersionedKeyValue(key= movie_id, value= movie_data.dict(), version= version)
                self.kv_client.put(new_vkv)
                return  # Success!

            except Exception as e:
                # 3. Handle Conflicts or Network Failures
                retries += 1
                if retries == self.max_retries:
                    raise RuntimeError(f"Failed to update movie {movie_id} after {retries} attempts: {e}") from e
                
                # Exponential backoff with jitter: 0.1s, 0.2s, 0.4s... + random noise
                wait_time = (2 ** retries * 0.1) + (random.uniform(0, 0.1))
                time.sleep(wait_time)
                # Loop continues: it will re-get the version and try again
    
    def exists(self, event_id):
        try:
            vkv = self.kv_client.get(event_id)
            return vkv is not None
        except:
            return False