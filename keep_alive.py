from flask import Flask
from threading import Thread

app = Flask("")

@app.route("/")
def home():
    return "🌸 Gul savdo boti ishlayapti!"

def keep_alive():
    t = Thread(target=lambda: app.run(host="0.0.0.0", port=8080), daemon=True)
    t.start()
