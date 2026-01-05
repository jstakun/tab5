try:
  import usocket as socket
except:
  import socket
import network
import esp
esp.osdebug(None)
import uos
import ujson
import sys
import os

SSID = 'AP-M5DiabConf'
PASSWORD = '123456789'
CONFIG = 'config'
CONFIG_FILE = 'config.json'

DEFAULT_CONFIG = {
    "config": 0,
    "brightness": 1,
    "screen-mode": 0,
    "api-endpoint": "https://www.gms-world.net/s/diabetes/1/api/v1",
    "api-token": "",
    "locale":"",
    "min": 75,
    "max": 180,
    "emergencyMin": 55,
    "emergencyMax": 250, 
    "timezone":"+02:00",
    "beeper": 0,
    "beeperStartTime": "00:00:00",
    "beeperEndTime": "23:59:59",
    "oldData": 15,
    "oldDataEmergenc": 1440
}

ipconfig = None

def saveConfigFile(config):
  try:
    with open(CONFIG_FILE, 'w') as confFile:
      ujson.dump(config, confFile) 
    print("Successfully saved config file")
  except Exception as e:
    sys.print_exception(e) 

def readConfigFile():
  try:
    with open(CONFIG_FILE, 'r') as confFile:
       return ujson.loads(confFile.read())
  except Exception as e:
    sys.print_exception(e) 
    return DEFAULT_CONFIG    

def randstr(length=20):
  source = 'abcdefghijklmnopqrstuvwxyz1234567890'
  return ''.join([source[x] for x in [(uos.urandom(1)[0] % len(source)) for _ in range(length)]])

def readHtmlFile(filename):
  try:
    with open(filename, 'r') as htmlFile:
      html = htmlFile.read()
    return html
  except Exception as e:
    sys.print_exception(e) 
    return "<html><body>Error loading page</body></html>"
  
def readHtmlConfigFile(filename):
  try:
    with open(filename, 'r') as htmlFile:
      html = htmlFile.read()
    config = readConfigFile()
    ignore = ["config","brightness","screen-mode","beeper","locale"]
    if config["beeper"] == 0:
      config["beeper_disabled"] = "selected"
      config["beeper_enabled"] = ""
    elif config["beeper"] == 1:
      config["beeper_enabled"] = "selected"
      config["beeper_disabled"] = ""    
    ssid = ""
    wifi_password = ""
    for key, value in config.items():
      if key in ignore:
        continue
      placeholder = "{{" + key + "}}"
      if placeholder in html:
        html = html.replace(placeholder, str(value))
      elif isinstance(value, str) and value != "":
        print("Wifi placeholder: " + placeholder)
        ssid = key
        wifi_password = value
    html = html.replace("{{ssid}}", ssid)
    html = html.replace("{{wifi_password}}", wifi_password)  
    return html
  except Exception as e:
    sys.print_exception(e)
    return "<html><body>Error loading page</body></html>"  

def unquote(string):
    if not string:
        return b''

    if isinstance(string, str):
        string = string.encode('utf-8')

    bits = string.split(b'%')
    if len(bits) == 1:
        return string

    res = bytearray(bits[0])
    append = res.append
    extend = res.extend

    for item in bits[1:]:
        try:
            append(int(item[:2], 16))
            extend(item[2:])
        except KeyError:
            append(b'%')
            extend(item)

    return bytes(res)

def open_access_point(successCallback):

  ap = network.WLAN(network.AP_IF)
  ap.active(True)
  ssid = SSID + "-" + randstr(5)
  ap.config(essid=ssid, password=PASSWORD)
  ap.config(max_clients=1) 

  while ap.active() == False:
    pass
  
  ipconfig = ap.ifconfig()

  print('AP config: ' + str(ipconfig))

  s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
  s.bind(('', 80))
  s.listen(5)

  configHtml = readHtmlConfigFile('config.html')
  successHtml = readHtmlFile('success.html')

  print('Web server is running on port 80')

  while True:
    conn, addr = s.accept()
    print('Got a connection from %s' % str(addr))
    request = conn.recv(1024)
    contentStr = request.decode()
    print('Content = %s' % contentStr)
    splittedRequest = contentStr.split()
    #rmethod = splittedRequest[0]
    rurl = splittedRequest[1]
  
    conn.send('HTTP/1.1 200 OK\n')
    conn.send('Content-Type: text/html\n')
    conn.send('Connection: close\n\n')

    if rurl.find("/config") != -1:
      splittedRequest = contentStr.split('\r\n')
      configParams = splittedRequest[len(splittedRequest)-1]
      print('Config params: ' + configParams) 
      entries = configParams.split('&') 
      wifi_ssid = None
      wifi_password = None
      config = {}
      for entry in entries:
        [k,v] = entry.split('=')
        value = unquote(v).decode()
        if k == 'ssid': wifi_ssid = value
        elif k == 'wifi_password': wifi_password = value  
        elif value.isdigit(): value = int(value) 
        if k != 'ssid' and k != 'wifi_password':
          config[k] = value
          print("Saved config parameter " + k)
      #Encode wifi password
      config[wifi_ssid] = wifi_password
      print("Saved config parameter " + wifi_ssid)
      config[CONFIG] = 1
      config["brightness"] = 1
      config["screen-mode"] = 0
      saveConfigFile(config)   
      
      successCallback()
      conn.send(successHtml)   
    else: 
      conn.send(configHtml)
      
    conn.close()