import requests
import base64
import cairosvg
import uuid
from pathlib import Path
from urllib.parse import urlencode

def generate_message_image(text, name="@Askoutbot"):
    params = {
        "name": name,
        "text": text,
        "bubble": "#000000",
        "background": "random",
        "avatar": "true"
    }

    base_url = "https://imessager.vercel.app/api/simple"
    query_string = urlencode(params)
    api_url = f"{base_url}?{query_string}"

    try:
        response = requests.get(api_url, timeout=10)
        data = response.json()
        if data.get("success"):
            file_id = uuid.uuid4().hex
            svg_path = Path(f"/tmp/{file_id}.svg")
            png_path = Path(f"/tmp/{file_id}.png")
            svg_data = base64.b64decode(data["base64"])
            svg_path.write_bytes(svg_data)
            cairosvg.svg2png(bytestring=svg_data, write_to=str(png_path), scale=3.0)
            return str(png_path)
    except Exception as ex:
        print(f"❌ Image generation failed: {ex}")
    return None
