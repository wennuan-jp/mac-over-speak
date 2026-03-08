import requests
import sys

def test_transcribe(audio_path, language=None):
    url = "http://127.0.0.1:8000/transcribe/"
    
    files = {
        'audio': open(audio_path, 'rb')
    }
    data = {}
    if language:
        data['language'] = language
        
    print(f"Sending {audio_path} to {url} (language={language})...")
    response = requests.post(url, files=files, data=data)
    
    if response.status_code == 200:
        print("Success!")
        print(response.json())
    else:
        print(f"Error {response.status_code}:")
        print(response.json())

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python api/test_client.py <audio_path> [language]")
        sys.exit(1)
        
    path = sys.argv[1]
    lang = sys.argv[2] if len(sys.argv) > 2 else None
    test_transcribe(path, lang)
