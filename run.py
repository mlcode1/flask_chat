from app import create_app, socketio

app = create_app()

if __name__ == "__main__":
    # 使用 socketio.run() 而不是 app.run()，以支持 WebSocket
    socketio.run(app, debug=True, host="0.0.0.0", port=8080, allow_unsafe_werkzeug=True)
