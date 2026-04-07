from flask import Flask
import socket

app = Flask(__name__)

@app.route('/')
def hello():
    html = """
    <html>
    <head><title>Mi App Docker</title></head>
    <body style="font-family: Arial; text-align: center; padding: 50px;">
        <h1 style="color: #028090;">¡Hola desde Docker! 🐳</h1>
        <p><strong>Hostname:</strong> {hostname}</p>
        
        <hr>
        <p>Aplicación containerizada con éxito</p>
    </body>
    </html>
    """
    return html.format(hostname=socket.gethostname())

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
