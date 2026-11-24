import argparse
import logging
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8000);p.add_argument('--host',default='127.0.0.1');a=p.parse_args()
logging.basicConfig(level=logging.INFO,format='%(asctime)s %(name)s %(levelname)s %(message)s')
uvicorn.run('marketlens.app:app',host=a.host,port=a.port)
