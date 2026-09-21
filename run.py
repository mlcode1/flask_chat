import eventlet
eventlet.monkey_patch(thread=True, socket=True, time=True, select=True, os=True)

import warnings
warnings.filterwarnings('ignore', category=DeprecationWarning)
warnings.filterwarnings('ignore', message='.*urllib3 v3.*')
warnings.filterwarnings('ignore', message='.*RLock.*greened.*')

from app import create_app, socketio

app = create_app()

if __name__ == "__main__":
    socketio.run(app, debug=True, host="0.0.0.0", port=8080,
                 allow_unsafe_werkzeug=True, log_output=True,
                 use_reloader=False)
