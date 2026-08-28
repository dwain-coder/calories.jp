import urllib.request
import urllib.parse
import json
import sys
import codecs

sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())

query = """
SELECT ?food ?foodLabel ?foodDescription WHERE {
  ?food wdt:P31/wdt:P279* wd:Q2095. 
  SERVICE wikibase:label { bd:serviceParam wikibase:language "ja,en". }
}
LIMIT 5
"""

url = 'https://query.wikidata.org/sparql?query=' + urllib.parse.quote(query) + '&format=json'
req = urllib.request.Request(url, headers={'User-Agent': 'DatasetManagerBot/1.0', 'Accept': 'application/sparql-results+json'})
try:
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
        for result in data['results']['bindings']:
            print(result.get('foodLabel', {}).get('value', 'Unknown'))
except Exception as e:
    print('Error:', e)
