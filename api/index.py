from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import re
import html
from urllib.parse import quote
from markdown import markdown

app = Flask(__name__)
CORS(app)

headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

def get_html(url):
    return requests.get(url, headers=headers).text

@app.route("/")
def home():
    return jsonify({"message": "Welcome to MAL API. Go to /docs for documentation."})

@app.route("/docs")
def docs():
    path = os.path.join(os.path.dirname(__file__), "..", "docs.md")
    if not os.path.exists(path):
        return "Documentation not found", 404

    with open(path, "r", encoding="utf-8") as f:
        html_content = markdown(f.read(), extensions=['fenced_code', 'tables'])

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>MyAnimeList API Docs</title>
        <style>
            :root {{
                color-scheme: light dark;
            }}
            body {{
                font-family: "Segoe UI", "Helvetica Neue", sans-serif;
                background: #f9f9f9;
                color: #333;
                margin: auto;
                max-width: 900px;
                padding: 2rem;
                line-height: 1.7;
            }}
            h1, h2, h3 {{
                border-bottom: 1px solid #ddd;
                padding-bottom: .3rem;
                margin-top: 2rem;
            }}
            code {{
                background: #eee;
                padding: 0.2em 0.4em;
                border-radius: 5px;
                font-family: monospace;
            }}
            pre {{
                background: #f4f4f4;
                padding: 1em;
                border-radius: 8px;
                overflow-x: auto;
                font-size: 0.95em;
            }}
            table {{
                border-collapse: collapse;
                width: 100%;
                margin: 1em 0;
            }}
            th, td {{
                border: 1px solid #ccc;
                padding: 10px;
                text-align: left;
            }}
            th {{
                background-color: #f0f0f0;
            }}
            a {{
                color: #007bff;
                text-decoration: none;
            }}
            a:hover {{
                text-decoration: underline;
            }}
        </style>
    </head>
    <body>
        {html_content}
    </body>
    </html>
    """

@app.route("/mal", methods=["GET"])
def mal_search():
    data = request.args.get("data")
    query = request.args.get("query")
    character_index = int(request.args.get("character", 1)) - 1

    if not data or not query:
        return jsonify({"error": "Missing 'data' or 'query' parameter"}), 400

    try:
        if data.lower() == "character":
            search_html = get_html(f"https://myanimelist.net/character.php?q={quote(query)}&cat=character")
            links = re.findall(r'<div class="picSurround">.*?<a href="(https://myanimelist\.net/character/\d+/[^"]+)"', search_html, re.DOTALL)

            if not links or character_index >= len(links):
                return jsonify({"error": "Character not found or index out of range"}), 404

            url = links[character_index]
            page = get_html(url)

            img_match = re.search(r'<div style="text-align: center;">.*?<img.*?(?:data-src|src)="([^"]+)"', page, re.DOTALL)
            img_url = img_match.group(1) if img_match else None

            td = re.search(r'<td valign="top" style="padding-left: 5px;">(.*?)</td>', page, re.DOTALL)
            html_block = td.group(1) if td else ""

            h2 = re.search(r'<h2.*?>(.*?)</h2>', html_block, re.DOTALL)
            title = html.unescape(re.sub(r'<.*?>', '', h2.group(1)).strip()) if h2 else "No title"

            desc_html = re.split(r'</h2>', html_block, 1)[1] if '</h2>' in html_block else ""
            spoiler = re.search(r'<div class="spoiler">(.*?)</div>', page, re.DOTALL)
            if spoiler:
                desc_html += " " + spoiler.group(1)

            desc = html.unescape(re.sub(r'<.*?>', '', desc_html)).strip()
            desc = re.split(r'Voice Actors|Animeography|Member Favorites', desc)[0].strip()

            return jsonify({
                "title": title,
                "image": img_url,
                "description": desc[:2000] + "...",
                "link": url
            })

        # Anime or Manga
        search_url = f'https://myanimelist.net/{data}.php?q={quote(query)}&cat={data}'
        html_data = get_html(search_url)
        link_match = re.search('<a class="hoverinfo_trigger" href="(.*?)"', html_data)

        if not link_match:
            return jsonify({"error": "No result found"}), 404

        result_url = link_match.group(1)
        page_data = get_html(result_url)

        output = {
            "cover": re.search('<meta property="og:image" content="(.*?)">', page_data).group(1),
            "link": result_url,
            "info": []
        }

        trailer = re.search(r'href="https://www.youtube.com/embed/(.*?)\?', page_data)
        if trailer:
            output["trailer"] = f"https://youtu.be/{trailer.group(1)}"

        description = re.search('<meta property="og:description" content="(.*?)">', page_data)
        if description:
            output["synopsis"] = description.group(1)

        data_blocks = re.findall('<span class="dark_text">(.*?)</div>', page_data, re.DOTALL)
        for block in [re.sub("<small>(.*?)</small>", "", x, flags=re.DOTALL) for x in data_blocks]:
            text = html.unescape(" ".join(re.sub("<.*?>", "", block).split()))
            if "None found, add some" in text:
                continue
            if "Genres" in text:
                genres_raw = text[8:].replace(" ", "").split(",")
                genre_clean = ", ".join([" ".join(re.findall('[A-Z][^A-Z]*', g)) for g in genres_raw])
                output["info"].append(f"Genres: {genre_clean}")
            elif "Score" in text:
                score_parts = text.split()
                score = score_parts[1][:4] if len(score_parts[1]) == 5 else score_parts[1]
                output["info"].append(f"Score: {score}")
            else:
                output["info"].append(text)

        return jsonify(output)

    except Exception as e:
        return jsonify({"error": str(e)}), 500
