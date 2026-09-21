"""Start the Sourcing Decision Room.

Locally this binds to 127.0.0.1 so nothing is exposed by accident. On a platform
such as Railway, PORT is set in the environment; that is the signal to listen on
every interface instead.
"""
import argparse
import getpass
import os

import uvicorn

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--prompt-key', action='store_true',
                        help='Read a hidden runtime secret; never save it')
    parser.add_argument('--port', type=int, default=int(os.getenv('PORT', '8000')))
    parser.add_argument('--host', default=os.getenv('HOST', '0.0.0.0' if os.getenv('PORT') else '127.0.0.1'))
    args = parser.parse_args()
    if args.prompt_key:
        os.environ['GOOGLE_API_KEY'] = getpass.getpass('Google API key (hidden, runtime only): ')
    # Behind a platform proxy the container is only reachable through that proxy, so
    # its X-Forwarded-* headers are the truth about scheme and host.
    behind_proxy = bool(os.getenv('PORT'))
    uvicorn.run("backend.app.main:app", host=args.host, port=args.port, reload=False, access_log=False,
                proxy_headers=True,
                forwarded_allow_ips=os.getenv('FORWARDED_ALLOW_IPS', '*' if behind_proxy else '127.0.0.1'))
