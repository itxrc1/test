import requests
import base64
import cairosvg
import uuid
from pathlib import Path
from urllib.parse import urlencode

def generate_message_image(text, name="@Askoutbot", compact=True):
    # Use smaller dimensions for more prominent bubble
    width = "500" if compact else "800"
    height = "400" if compact else "300"
    
    params = {
        "name": name,
        "text": text,
        "bubble": "#000000",
        "background": "random-gradient",
        "avatar": "false",
        "width": width,      # New parameter
        "height": height     # New parameter
    }
    
    base_url = "https://v0-chat-bubble-generator-two.vercel.app/api/simple"
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
            
            # Higher scale for better quality with smaller dimensions
            cairosvg.svg2png(
                bytestring=svg_data, 
                write_to=str(png_path), 
                scale=4.0  # Increased scale
            )
            
            return str(png_path)
            
    except Exception as ex:
        print(f"❌ Image generation failed: {ex}")
    
    return None
