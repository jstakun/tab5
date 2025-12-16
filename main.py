#UiFlow2 https://uiflow-micropython.readthedocs.io/en/develop/

import M5
import ntptime
from hardware import WDT, I2C, Pin
import machine
import requests2
import math
import time
import network
import sys
import _thread
import utime
from collections import OrderedDict
import re
import ap
import ujson
from unit import ENVUnit, RGBUnit

EMERGENCY_PAUSE_INTERVAL = 1800  #sec = 30 mins
MODES = ["full_elapsed", "full_date", "full_battery", "basic", "flip_full_elapsed", "flip_full_date", "flip_full_battery", "chart", "flip_chart"]
SGVDICT_FILE = 'sgvdict.txt'
RESPONSE_FILE = 'response.json'
BACKEND_TIMEOUT_MS = 30000 #max 60000
MAX_SAVED_ENTRIES = 10
YEAR = 2025
SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720
MIN_SWIPE_DIST = 250  # Minimum distance in pixels to count as a swipe

drawScreenLock = _thread.allocate_lock()

def getBatteryLevel():
  return 100 #M5.Power.getBatteryLevel() no battery present 

def isOlderThan(date_str, mins, now_seconds, print_time=False): 
  the_date = getDateTuple(date_str)
  the_date_seconds = utime.mktime(the_date)
  #print("Date: " + str(the_date) + " - " + str(the_date_seconds) + ", Now: " + str(now_seconds))
  diff = (now_seconds - the_date_seconds)
  if print_time == True:
     printTime(diff, prefix='Entry read', suffix='ago')
  return (diff > (60 * mins) and getBatteryLevel() >= 5)  

def getDateTuple(date_str):
  [yyyy, mm, dd] = [int(i) for i in date_str.split('T')[0].split('-')]
  [HH, MM, SS] = [int(i) for i in date_str.split('T')[1].split(':')]
  return (yyyy, mm, dd, HH, MM, SS, 0, 0)    

def printTime(seconds, prefix='', suffix=''):
  m, s = divmod(seconds, 60)
  h, m = divmod(m, 60)
  print(prefix + ' {:02d}:{:02d}:{:02d} '.format(h, m, s) + suffix)  

def saveResponseFile():
  global response
  with open(RESPONSE_FILE, 'w') as responseFile:
    ujson.dump(response, responseFile) 
 
def readResponseFile():
  global response
  try:
    with open(RESPONSE_FILE, 'r') as responseFile:
      response = ujson.loads(responseFile.read())
  except Exception as e:
    sys.print_exception(e)
    saveError(e)
    response = None
    
def saveSgvFile(sgvdict):
  items = []
  for key in sgvdict:
    items.append(str(key) + ':' + str(sgvdict[key]))
  content = '\n'.join(items)
  with open(SGVDICT_FILE, 'w') as file:
    file.write(content)

def readSgvFile():
  d = OrderedDict()
  try: 
    with open(SGVDICT_FILE, 'r') as f:
      sgvFile = f.read()
    if sgvFile != None:
      entries = sgvFile.split('\n')
      for entry in entries:
        if ":" in entry:
          [s, v] = [int(i) for i in entry.split(':')]
          d.update({s: v})   
  except Exception as e:
    sys.print_exception(e)
    saveError(e)
  return d 

def saveError(e):
  now = utime.ticks_cpu()
  filename = "error" + str(now) + ".txt"
  with open(filename, 'w') as file:
    sys.print_exception(e, file)

def persistEntries():
  global response, sgvDict
  saveResponseFile()
  d = OrderedDict()
  seconds = -1
  for index, entry in enumerate(response):
    the_date = getDateTuple(entry['date'])  
    seconds = utime.mktime(the_date)
    d.update({seconds: entry['sgv']})
  
  dictLen = len(d)  
  for key in sgvDict:
    if key < seconds and dictLen < MAX_SAVED_ENTRIES:
       d.update({key: sgvDict[key]})
    elif dictLen >= MAX_SAVED_ENTRIES:
      break  
    dictLen = len(d)

  sgvDict = d
  saveSgvFile(d)
  print('\nPersisted ' + str(dictLen) + " sgv entries")

def checkBeeper():
  global USE_BEEPER, BEEPER_START_TIME, BEEPER_END_TIME, secondsDiff
  try:   
    if (USE_BEEPER == 1 and getBatteryLevel() >= 5):
      d = utime.localtime(0)
      now_datetime = utime.localtime(utime.time()) 
      if now_datetime[0] < YEAR:
        raise ValueError('Invalid datetime: ' + str(now_datetime))
      now = utime.mktime((now_datetime[0], now_datetime[1], now_datetime[2], now_datetime[3], now_datetime[4], now_datetime[5],0,0))
      localtime = utime.localtime(now + secondsDiff)
      
      c = list(d)
      c[3] = localtime[3]
      c[4] = localtime[4]
      c[5] = localtime[5]

      d1 = list(d)
      [HH, MM, SS] = [int(i) for i in BEEPER_START_TIME.split(':')]
      d1[3] = HH
      d1[4] = MM
      d1[5] = SS

      d2 = list(d)
      [HH, MM, SS] = [int(i) for i in BEEPER_END_TIME.split(':')]
      d2[3] = HH
      d2[4] = MM
      d2[5] = SS

      #print("Compare start: " + str(d1) + ", end: " + str(d2) + ", current: " + str(c))
      
      if tuple(d1) < tuple(d2):
         #d1 start | current | d2 end 
         return tuple(c) > tuple(d1) and tuple(c) < tuple(d2)
      else:
         # current | d2 end | or | d1 start | current 
         return tuple(c) > tuple(d1) or tuple(c) < tuple(d2)
    else:
      return False 
  except Exception as e:
    sys.print_exception(e)
    saveError(e)
    return False   

def getRtcDatetime():
  now_datetime = None
  for i in range(3):
    now_datetime = utime.localtime(utime.time())
    if now_datetime[0] >= YEAR:
      return now_datetime
  raise ValueError('Invalid datetime: ' + str(now_datetime))

# gui methods ----

def printCenteredText(msg, mode, font=M5.Display.FONTS.DejaVu72, backgroundColor=M5.Display.COLOR.BLACK, textColor=M5.Display.COLOR.WHITE, clear=True):  
  if mode >= 4:
    M5.Display.setRotation(3)
  else:        
    M5.Display.setRotation(1)
    
  if clear:
    M5.Display.clear(backgroundColor)
        
  M5.Display.setFont(font)
    
  M5.Display.setTextColor(textColor, backgroundColor)
    
  w = M5.Display.textWidth(msg)
  f = M5.Display.fontHeight()
  x = int((SCREEN_WIDTH-w)/2)
  y = int((SCREEN_HEIGHT-f)/2)

  M5.Display.drawString(msg, x, y)

def printText(msg, x, y, font=None, backgroundColor=M5.Display.COLOR.BLACK, textColor=M5.Display.COLOR.DARKGREY, rotate=1, silent=False):
  M5.Display.setRotation(rotate)  
    
  if font != None:       
    M5.Display.setFont(font)
    
  M5.Display.setTextColor(textColor, backgroundColor)
    
  M5.Display.drawString(msg, x, y)
  
  if silent == False:
    print("Printing " + msg)

def drawDirectionV2(cx, cy, radius=48, angle_degrees=0, gap=16, circle_color=M5.Display.COLOR.BLACK, tri_color=M5.Display.COLOR.DARKGREY, ydiff=0):
    #cx - Center X coordinate
    #cy - Center Y coordinate
    #radius - Radius of the circle
    #gap - Pixel gap
    #circle_color 
    #tri_color
    #ydiff - triangle distance 
    
    # 1. Clear previous state
    M5.Lcd.fillCircle(cx, cy, radius, circle_color)

    r_tri = radius - gap
    
    # 2. Adjust the Angle
    # We subtract 90 degrees so that Input 0 aligns with "Up" (270 deg / -90 deg on circle)
    # We add the user input 'angle_degrees' to rotate clockwise from there.
    adjusted_angle = angle_degrees - 90
    rotation_rad = adjusted_angle * (math.pi / 180)

    # 3. Calculate Vertices
    
    # Vertex 1: The "Pointer"
    v1_angle = rotation_rad
    x1 = cx + int(r_tri * math.cos(v1_angle))
    y1 = cy + int(r_tri * math.sin(v1_angle))

    # Vertex 2: +120 degrees from pointer
    v2_angle = rotation_rad + (2 * math.pi / 3)
    x2 = cx + int(r_tri * math.cos(v2_angle))
    y2 = cy + int(r_tri * math.sin(v2_angle))

    # Vertex 3: +240 degrees from pointer
    v3_angle = rotation_rad + (4 * math.pi / 3)
    x3 = cx + int(r_tri * math.cos(v3_angle))
    y3 = cy + int(r_tri * math.sin(v3_angle))

    # 4. Draw
    if ydiff == 0:
      M5.Lcd.fillTriangle(x1, y1, x2, y2, x3, y3, tri_color)
    else:  
      M5.Lcd.fillTriangle(x1, y1-ydiff, x2, y2-ydiff, x3, y3-ydiff, tri_color)
      M5.Lcd.fillTriangle(x1, y1+ydiff, x2, y2+ydiff, x3, y3+ydiff, tri_color)

def printLocaltime(mode, secondsDiff, localtime=None, useLock=False, silent=False):
  try: 
    if localtime == None:
      now_datetime = getRtcDatetime()
      now = utime.mktime((now_datetime[0], now_datetime[1], now_datetime[2], now_datetime[3], now_datetime[4], now_datetime[5],0,0))  + secondsDiff
      localtime = utime.localtime(now)
    h = str(localtime[3])
    if (localtime[3] < 10): h = "0" + h   
    m = str(localtime[4])
    if (localtime[4] < 10): m = "0" + m
    s = str(localtime[5])
    if (localtime[5] < 10): s = "0" + s
    timeStr = h + ":" + m + ":" + s
    locked = False 
    if useLock == False and drawScreenLock.locked() == False:
      locked = drawScreenLock.acquire()
    if locked == True or useLock == True:
      rotate = 1
      if mode >= 4:
        rotate = 3
      M5.Display.setFont(M5.Display.FONTS.DejaVu72)  
      M5.Display.setTextSize(3)
      w = M5.Display.textWidth(timeStr)  
      printText(timeStr, int((SCREEN_WIDTH-w)/2), 10, silent=silent, rotate=rotate)  
      M5.Display.setTextSize(1)
      if useLock == False and locked == True:
        drawScreenLock.release()
  except Exception as e:
    sys.print_exception(e)
    saveError(e)

prevStr = {}

def drawScreen(newestEntry, noNetwork=False, clear=True):
  global response, mode, brightness, emergency, emergencyPause, MIN, MAX, EMERGENCY_MIN, EMERGENCY_MAX, startTime, rgbUnit, secondsDiff, OLD_DATA, OLD_DATA_EMERGENCY, envUnit, secondsDiff, humidityStr, pressureStr, tempStr, firstRun, prevStr
  
  #1280 x 720
  
  now_datetime = getRtcDatetime()
    
  locked = drawScreenLock.acquire()

  if locked == True: 

    currentMode = mode

    if firstRun == True:
      clear = True

    s = utime.time()
    print('Printing screen in ' + MODES[currentMode] + ' mode')
  
    sgv = newestEntry['sgv']
    sgvStr = str(sgv)
  
    directionStr = newestEntry['direction']
    sgvDateStr = newestEntry['date']
  
    now = utime.mktime((now_datetime[0], now_datetime[1], now_datetime[2], now_datetime[3], now_datetime[4], now_datetime[5],0,0))  + secondsDiff
    
    tooOld = False
    try:
      tooOld = isOlderThan(sgvDateStr, OLD_DATA, now, print_time=True)
    except Exception as e:
      sys.print_exception(e)
      saveError(e)
    #print("Is sgv data older than " + str(OLD_DATA) + " minutes?", tooOld)  

    emergencyNew = None
  
    if tooOld: backgroundColor=M5.Display.COLOR.DARKGREY; emergencyNew=False
    elif sgv <= EMERGENCY_MIN: backgroundColor=M5.Display.COLOR.RED; emergencyNew=(utime.time() > emergencyPause and not tooOld)  
    elif sgv >= (MIN-10) and sgv < MIN and directionStr.endswith("Up"): backgroundColor=M5.Display.COLOR.DARKGREEN; emergencyNew=False
    elif sgv > EMERGENCY_MIN and sgv < MIN: backgroundColor=M5.Display.COLOR.RED; emergencyNew=False
    elif sgv >= MIN and sgv <= MAX: backgroundColor=M5.Display.COLOR.DARKGREEN; emergencyNew=False 
    elif sgv > MAX and sgv <= (MAX+10) and directionStr.endswith("Down"): backgroundColor=M5.Display.COLOR.DARKGREEN; emergencyNew=False
    elif sgv > MAX and sgv <= EMERGENCY_MAX: backgroundColor=M5.Display.COLOR.ORANGE; emergencyNew=False
    elif sgv > EMERGENCY_MAX: backgroundColor=M5.Display.COLOR.ORANGE; emergencyNew=(utime.time() > emergencyPause and not tooOld)  
  
    #battery level emergency
    batteryLevel = getBatteryLevel()
    uptime = utime.time() - startTime  
    if (batteryLevel < 10 and batteryLevel > 0 and uptime > 300) and (utime.time() > emergencyPause) and not M5.Power.isCharging(): 
      emergencyNew = True
      if currentMode < 4 or currentMode == 7: currentMode = 2
      else: currentMode = 6
      clear = True

    #old data emergency
    if utime.time() > emergencyPause and isOlderThan(sgvDateStr, OLD_DATA_EMERGENCY, now):
      emergencyNew = True
      clear = True   

    emergency = emergencyNew  

    if emergency == False and rgbUnit != None:
      rgbUnit.set_color(0, M5.Display.COLOR.BLACK)
      rgbUnit.set_color(1, backgroundColor)
      rgbUnit.set_color(2, M5.Display.COLOR.BLACK)

    #if emergency change to one of full modes 
    if emergency == True and (currentMode == 3 or currentMode == 7): currentMode = 0
  
    if noNetwork == False and "ago" in newestEntry and (currentMode == 0 or currentMode == 4): 
      dateStr = newestEntry['ago']
    elif currentMode == 2 or currentMode == 6:
      if batteryLevel >= 0:
       dateStr = "Battery: " + str(batteryLevel) + "%"
      else: 
       dateStr = "Battery level unknown"
    else:   
      dateStr = sgvDateStr.replace("T", " ")[:-3] #remove seconds
  
    if not tooOld and directionStr == 'DoubleUp' and sgv+20>=MAX and sgv<MAX: arrowColor = M5.Display.COLOR.ORANGE
    elif not tooOld and directionStr == 'DoubleUp' and sgv>=MAX: arrowColor = M5.Display.COLOR.RED
    elif not tooOld and directionStr == 'DoubleDown' and sgv-20<=MIN: arrowColor = M5.Display.COLOR.RED
    elif not tooOld and directionStr.endswith('Up') and sgv+10>=MAX and sgv<MAX: arrowColor = M5.Display.COLOR.ORANGE
    elif not tooOld and directionStr.endswith('Down') and sgv-10<=MIN: arrowColor = M5.Display.COLOR.RED
    else: arrowColor = backgroundColor  

    try:
      if envUnit != None:
        tempStr = "%.0f" % envUnit.read_temperature()
        pressureStr = "%.0f" % envUnit.read_pressure()
        humidityStr = "%.0f" % envUnit.read_humidity()
    except Exception as e:
      sys.print_exception(e)
      #saveError(e)

    sgvDiff = 0
    if len(response) > 1: 
       sgvDiff = sgv - response[1]['sgv']
       if sgvDiff >= 100: sgvDiff = 99
       elif sgvDiff <= -100: sgvDiff = -99
    sgvDiffStr = str(sgvDiff)
    if sgvDiff > 0: sgvDiffStr = "+" + sgvDiffStr
    sgvDiffStr = "(" + sgvDiffStr + ")"

    rotate = 1
    if mode >= 4:
      rotate = 3
    
    M5.Display.setRotation(rotate)  

    if clear == True:
       M5.Display.clear(M5.Display.COLOR.BLACK)
       prevStr = {}

    #draw current time
    printLocaltime(mode, secondsDiff, useLock=True)  
 
    #draw battery
    #M5.Display.setFont(M5.Display.FONTS.DejaVu24)
    #textColor = batteryTextColor
    #w = M5.Display.textWidth(batteryStr)
    #printText(batteryStr, int(SCREEN_WIDTH - w - 10), 12, font=M5.Display.FONTS.DejaVu24, rotate=rotate) 
    
    #draw sgv
    M5.Display.setFont(M5.Display.FONTS.DejaVu72)  
    M5.Display.setTextSize(4)
    x = 10
    w = M5.Display.textWidth(sgvStr) 
    f = M5.Display.fontHeight()
    y = int((SCREEN_HEIGHT - f) / 2) + 30
    if clear == True:
       M5.Display.drawLine(10, y, SCREEN_WIDTH-10, y, M5.Display.COLOR.DARKGREY)
    y += 30
    drawSgv = False
    if "sgvStr" in prevStr and prevStr["sgvStr"] != sgvStr:
       M5.Display.fillRect(x, y, M5.Display.textWidth("888"), f, M5.Display.COLOR.BLACK)
       drawSgv = True
    if drawSgv == True or "sgvStr" not in prevStr:  
       printText(sgvStr, x, y, textColor=backgroundColor, rotate=rotate)
    M5.Display.setTextSize(1)
    
    ly = y+f-100
    if drawSgv == True or "sgvStr" not in prevStr:  
       sgvLabelStr = "mg/dL"  
       printText(sgvLabelStr, x+w, ly, font=M5.Display.FONTS.DejaVu40, rotate=rotate)
    
    prevStr["sgvStr"] = sgvStr

    #draw sgv diff
    radius = 60
    gap = 0
    M5.Display.setFont(M5.Display.FONTS.DejaVu72)  
    M5.Display.setTextSize(2)
    f = M5.Display.fontHeight()
    textColor = M5.Display.COLOR.DARKGREY
    if math.fabs(sgvDiff) >= 10 and backgroundColor != M5.Display.COLOR.RED and not tooOld: textColor = M5.Display.COLOR.RED
    w = M5.Display.textWidth(sgvDiffStr)
    x = SCREEN_WIDTH - 20 - (2*radius) - gap - w
    drawSgvDiff = False
    if "sgvDiffStr" in prevStr:
       fx = SCREEN_WIDTH - 20 - (2*radius) - gap - M5.Display.textWidth(prevStr["sgvDiffStr"])
       if prevStr["sgvDiffStr"] != sgvDiffStr:
         M5.Display.fillRect(fx, y, M5.Display.textWidth(prevStr["sgvDiffStr"]), f+5, M5.Display.COLOR.BLACK)
         drawSgvDiff = True
    if drawSgvDiff == True or "sgvDiffStr" not in prevStr:  
       printText(sgvDiffStr, x, y+20, textColor=textColor, rotate=rotate)
    M5.Display.setTextSize(1)
    lx = x
    prevStr["sgvDiffStr"] = sgvDiffStr
    
    #draw arrow
    x += w + gap + radius
    y += int(f / 2) 

    if "directionStr" not in directionStr or prevStr["directionStr"] != directionStr:     
       if directionStr == 'DoubleUp': drawDirectionV2(x, y+20, radius=radius, tri_color=arrowColor, ydiff=16)
       elif directionStr == 'DoubleDown': drawDirectionV2(x, y+20, radius=radius, angle_degrees=180, tri_color=arrowColor, ydiff=16) 
       elif directionStr == 'SingleUp': drawDirectionV2(x, y+20, radius=radius, tri_color=arrowColor)
       elif directionStr == 'SingleDown': drawDirectionV2(x, y+20, radius=radius, angle_degrees=180, tri_color=arrowColor)
       elif directionStr == 'Flat': drawDirectionV2(x, y+20, radius=radius, angle_degrees=90, tri_color=arrowColor)
       elif directionStr == 'FortyFiveUp': drawDirectionV2(x, y+20, radius=radius, angle_degrees=45, tri_color=arrowColor)
       elif directionStr == 'FortyFiveDown': drawDirectionV2(x, y+20, radius=radius, angle_degrees=135, tri_color=arrowColor)
    prevStr["directionStr"] = directionStr
 
    #draw dateStr
    M5.Display.setFont(M5.Display.FONTS.DejaVu40)
    textColor = M5.Display.COLOR.DARKGREY
    if isOlderThan(sgvDateStr, 10, now): 
       textColor = M5.Display.COLOR.RED
    w = M5.Display.textWidth(dateStr)
    x = lx + int((SCREEN_WIDTH-lx-w)/2)
    drawDateStr = False
    if "dateStr" in prevStr and prevStr["dateStr"] != dateStr:
       fx += int((SCREEN_WIDTH-fx-M5.Display.textWidth(prevStr["dateStr"]))/2)
       M5.Display.fillRect(fx, ly, M5.Display.textWidth(prevStr["dateStr"]), M5.Display.fontHeight(), M5.Display.COLOR.BLACK)
       drawDateStr = True
    if drawDateStr == True or "dateStr" not in prevStr:  
       printText(dateStr, x, ly, textColor=textColor, rotate=rotate)  
    prevStr["dateStr"] = dateStr

    y += f+55
    M5.Display.drawLine(10, y, SCREEN_WIDTH-10, y, M5.Display.COLOR.DARKGREY)
    y += 10

    #draw tempStr
    M5.Display.setFont(M5.Display.FONTS.DejaVu72)
    M5.Display.setTextSize(1.5)
    f = M5.Display.fontHeight()
    w = M5.Display.textWidth(tempStr)
    if "tempStr" not in prevStr or prevStr["tempStr"] != tempStr:
       printText(tempStr, 20, int(y+(SCREEN_HEIGHT-y-f)/2), rotate=rotate)
       printText("C", 20+w, int(y+(SCREEN_HEIGHT-y)/2)-20, font=M5.Display.FONTS.DejaVu40, rotate=rotate)
    prevStr["tempStr"] = tempStr

    #draw pressureStr
    M5.Display.setFont(M5.Display.FONTS.DejaVu72)
    M5.Display.setTextSize(1.5)
    f = M5.Display.fontHeight()
    w = M5.Display.textWidth(pressureStr)
    drawPressure = False
    if "pressureStr" in prevStr and prevStr["pressureStr"] != pressureStr:
       fx = int((SCREEN_WIDTH-M5.Display.textWidth(prevStr["pressureStr"]))/2)-60
       fy = int(y+(SCREEN_HEIGHT-y-f)/2)
       M5.Display.fillRect(fx, fy, M5.Display.textWidth(prevStr["pressureStr"]), f, M5.Display.COLOR.BLACK)
       drawPressure = True
    if "pressureStr" not in prevStr or drawPressure == True:   
       printText(pressureStr, int((SCREEN_WIDTH-w)/2)-60, int(y+(SCREEN_HEIGHT-y-f)/2), rotate=rotate)
       printText("hPa", int((SCREEN_WIDTH-w)/2)-60+w, int(y+(SCREEN_HEIGHT-y)/2)-20, font=M5.Display.FONTS.DejaVu40, rotate=rotate)
    prevStr["pressureStr"] = pressureStr

    #draw humidityStr
    M5.Display.setFont(M5.Display.FONTS.DejaVu72)
    M5.Display.setTextSize(1.5)
    f = M5.Display.fontHeight()
    w = M5.Display.textWidth(humidityStr)
    if "humidityStr" not in prevStr or prevStr["humidityStr"] != humidityStr:
       printText(humidityStr, SCREEN_WIDTH-w-20-50, int(y+(SCREEN_HEIGHT-y-f)/2), rotate=rotate)
       printText("%", SCREEN_WIDTH-20-50, int(y+(SCREEN_HEIGHT-y)/2)-20, font=M5.Display.FONTS.DejaVu40, rotate=rotate)
    prevStr["humidityStr"] = humidityStr

    if firstRun == True: firstRun = False

    drawScreenLock.release()
    print("Printing screen finished in " + str((utime.time() - s)) + " secs ...")  
  else:    
    print("Printing locked!")

# ------

def backendMonitor():
  global response, API_ENDPOINT, API_TOKEN, LOCALE, TIMEZONE, startTime, sgvDict, secondsDiff, backendResponseTimer, backendResponse, mode
  lastid = -1
  while True:
    try:
      print('Battery level: ' + str(getBatteryLevel()) + '%')
      printTime((utime.time() - startTime), prefix='Uptime is')
      print("Calling backend with timeout " + str(BACKEND_TIMEOUT_MS) + " ms ...")
      s = utime.time()
      backendResponseTimer.init(mode=machine.Timer.ONE_SHOT, period=BACKEND_TIMEOUT_MS+10000, callback=watchdogCallback)
      backendResponse = requests2.get(API_ENDPOINT + "/entries.json?count=10&waitfornextid=" + str(lastid) + "&timeout=" + str(BACKEND_TIMEOUT_MS), headers={'api-secret': API_TOKEN,'accept-language': LOCALE,'accept-charset': 'ascii', 'x-gms-tz': TIMEZONE})
      backendResponseTimer.deinit()
      response = backendResponse.json()
      backendResponse.close()
      printTime((utime.time() - s), prefix='Response received in')
      sgv = response[0]['sgv']
      sgvDate = response[0]['date']
      lastid = response[0]['id']
      print('Sgv:', sgv)
      print('Direction:', response[0]['direction'])
      print('Read: ' + sgvDate + ' (' + TIMEZONE + ')')
      sgvDiff = 0
      if len(response) > 1: sgvDiff = sgv - response[1]['sgv']
      print('Sgv diff from previous read:', sgvDiff)
      drawScreen(response[0], clear=False)
      _thread.start_new_thread(persistEntries, ())
      #persistEntries() 
    except Exception as e:
      backendResponseTimer.deinit()
      if backendResponse != None: backendResponse.close()
      lastid = -1
      sys.print_exception(e)
      #saveError(e)
      print('Battery level: ' + str(getBatteryLevel()) + '%')
      if response == None: readResponseFile()
      try: 
        if response != None and len(response) >= 1: 
          drawScreen(response[0], noNetwork=True, clear=False)
        else:
          printCenteredText("Network error! Please wait.", mode, backgroundColor=M5.Display.COLOR.RED, clear=True)
      except Exception as e:
        sys.print_exception(e)
        saveError(e)
      print('Backend call error. Retry in 5 secs ...')
      time.sleep(5)
    print('---------------------------')

def setEmergencyrgbUnitColor(setBeepColorIndex, beepColor):
  setBlackColorIndex = setBeepColorIndex-1
  if setBlackColorIndex == -1: setBlackColorIndex = 2
  #print('Colors: ' + str(setBlackColorIndex) + ' ' + str(setBeepColorIndex))
  if rgbUnit != None:
    rgbUnit.set_color(setBlackColorIndex, M5.Display.COLOR.BLACK)
    rgbUnit.set_color(setBeepColorIndex, beepColor)
        
def emergencyMonitor():
  global emergency, response, rgbUnit, beeperExecuted, EMERGENCY_MAX, EMERGENCY_MIN, OLD_DATA_EMERGENCY
  useBeeper = False
  set_colorIndex = 1
  
  while True:
    #print('Emergency monitor checking status')
    if emergency == True:
      batteryLevel = getBatteryLevel()
      sgv = response[0]['sgv']
      if batteryLevel < 10:
        print('Low battery level ' + str(batteryLevel) + "%!!!")
      elif sgv > EMERGENCY_MAX or sgv <= EMERGENCY_MIN:
        print('Emergency glucose level ' + str(sgv) + '!!!')
      else:
        print('SGV data is older than ' + str(OLD_DATA_EMERGENCY) + ' minutes!!!')  
      
      beepColor = M5.Display.COLOR.RED
      if sgv > EMERGENCY_MAX: beepColor = M5.Display.COLOR.ORANGE  

      setEmergencyrgbUnitColor(set_colorIndex, beepColor)
      set_colorIndex += 1
      if set_colorIndex > 2: set_colorIndex = 0 
      if beeperExecuted == False:
        useBeeper = checkBeeper()
      if useBeeper == True:
        M5.Power.setVibration(128) #Max 255
        M5.Power.setLed(255)
        time.sleep(1)
        M5.Power.setVibration(0)
        M5.Power.setLed(0)
        beeperExecuted = True   
        useBeeper = False 
      else:
        M5.Power.setLed(255)
        time.sleep(1)
        M5.Power.setLed(0)
      print("beeperExecuted=" + str(beeperExecuted) + ", useBeeper=" + str(useBeeper))              
    else:
      #print('No Emergency')
      beeperExecuted = False
      useBeeper = False
      set_colorIndex = 0
      time.sleep(1)

def accelCallback(t):
  global mode, response
  acceleration = M5.Imu.getAccel()
  #print("Current acceleration: " + str(acceleration))
  hasResponse = (response != None)
  if hasResponse and acceleration[0] > 1.0 and mode in range(0,3): mode += 4; drawScreen(response[0]) #change to 'Flip mode' #4,5,6
  elif hasResponse and acceleration[0] < -1.0 and mode in range(4,7): mode -= 4; drawScreen(response[0]) #change to 'Normal mode' #0,1,2
  elif hasResponse and acceleration[0] > 1.0 and mode == 7: mode = 8; drawScreen(response[0])
  elif hasResponse and acceleration[0] < -1.0 and mode == 8: mode = 7; drawScreen(response[0])

# --- State Variables ---
was_pressed = False
start_x = 0
start_y = 0
last_x = 0
last_y = 0

def touchPadCallback(t):
    global was_pressed, start_x, start_y, last_x, last_y
    
    M5.update()
    
    # check how many fingers are touching
    count = M5.Touch.getCount()
    
    # === STATE 1: TOUCHING ===
    if count > 0:
        curr_x = M5.Touch.getX()
        curr_y = M5.Touch.getY()
        
        # If this is the FIRST frame of the touch
        if not was_pressed:
            was_pressed = True
            start_x = curr_x
            start_y = curr_y
            print("Touch Start:", start_x, start_y)
            
        # Continuously update the "last known" position while dragging
        last_x = curr_x
        last_y = curr_y
        onTouchTap()

    # === STATE 2: RELEASED (Gesture End) ===
    elif count == 0 and was_pressed:
        was_pressed = False
        print("Touch Release at:", last_x, last_y)
        
        # Calculate distance moved
        dx = last_x - start_x
        dy = last_y - start_y
        
        # Determine Gesture
        # 1. Check if movement was significant enough
        if abs(dx) > abs(dy) and abs(dx) > MIN_SWIPE_DIST:
            if dx > 0:
                print(">>> SWIPE RIGHT >>>")
            else:
                print("<<< SWIPE LEFT <<<")
            onTouchSwipe(t)    
        elif abs(dy) > abs(dx) and abs(dy) > MIN_SWIPE_DIST:
            if dy > 0:
                print("vvv SWIPE DOWN vvv")
            else:
                print("^^^ SWIPE UP ^^^")
            onTouchSwipe(t)    
        else:
            print("--- TAP (No Swipe) ---")
            onTouchTap(saveConfig=True)


def watchdogCallback(t):
  global shuttingDown, backendResponse, rgbUnit, response, mode

  print('Restarting due to backend communication failure ...')
  if rgbUnit != None:
    rgbUnit.set_color(0, M5.Display.COLOR.BLACK)
    rgbUnit.set_color(1, M5.Display.COLOR.DARKGREY)
    rgbUnit.set_color(2, M5.Display.COLOR.BLACK)
  if backendResponse != None: backendResponse.close()
  WDT(timeout=1000)   
  shuttingDown = True
  printCenteredText("Restarting...", mode, backgroundColor=M5.Display.COLOR.RED, clear=True)

def localtimeCallback(t):
  global shuttingDown, mode, secondsDiff 
  if shuttingDown == False:
    printLocaltime(mode, secondsDiff, silent=True)

def onTouchTap(saveConfig=False):
  global emergency, emergencyPause
  if emergency == True:
    emergency = False
    emergencyPause = utime.time() + EMERGENCY_PAUSE_INTERVAL
  else:   
    global brightness, config
    brightness += 4
    if brightness > 255: brightness = 1
    M5.Widgets.setBrightness(brightness)
    config["brightness"] = brightness
    print("Setting brightness " + str(brightness))
    if saveConfig == True:
      ap.saveConfigFile(config)

def onTouchSwipe(t):
  global shuttingDown, mode, config
  print('Button B pressed')
  config[ap.CONFIG] = 0
  ap.saveConfigFile(config)
  WDT(timeout=1000)
  shuttingDown = True
  printCenteredText("Restarting...", mode, backgroundColor=M5.Display.COLOR.RED, clear=True)  

# main app code -------------------------------------------------------------------     

config = ap.readConfigFile()

mode = 0
if M5.Imu.getAccel()[0] > 1.0: mode = 4 #flip

firstRun = True

M5.begin()

brightness = 32
if config != None: brightness = config["brightness"]
M5.Widgets.setBrightness(brightness)
M5.Power.setLed(0)

printCenteredText("Starting...", mode, backgroundColor=M5.Display.COLOR.DARKGREY, clear=True)  

envUnit = None

try: 
   i2c0 = I2C(0, scl=Pin(54), sda=Pin(53), freq=40000)
   envUnit = ENVUnit(i2c=i2c0, type=3) 
   tempStr = "%.0f" % envUnit.read_temperature()
   pressureStr = "%.0f" % envUnit.read_pressure()
   humidityStr = "%.0f" % envUnit.read_humidity()
   print('Temperature:', tempStr)
   print('Humidity:', pressureStr)
   print('Pressure:', humidityStr) 
except Exception as e:
   print('Weather Monitoring Unit not found')
   sys.print_exception(e)

rgbUnit = None
try: 
   rgbUnit = RGBUnit((36, 26), 3)
   rgbUnit.set_color(0, M5.Display.COLOR.BLACK)     
   rgbUnit.set_color(1, M5.Display.COLOR.DARKGREY)
   rgbUnit.set_color(2, M5.Display.COLOR.BLACK)
except Exception as e:
   print('RGB Unit not found')
   sys.print_exception(e)

print('Starting ...')
print('System:', sys.implementation)

response = None
emergency = False
emergencyPause = 0
shuttingDown = False
backendResponse = None
beeperExecuted = False

if config == None or config[ap.CONFIG] == 0:
   printCenteredText("Connect AP ...", mode, backgroundColor=M5.Display.COLOR.RED, clear=True)
   print("Connect wifi " + ap.SSID)
   def reboot():
      global shuttingDown 
      print('Restarting after configuration change...')
      WDT(timeout=1000)   
      shuttingDown = True
      printCenteredText("Restarting...", mode, backgroundColor=M5.Display.COLOR.RED, clear=True)   
   ap.open_access_point(reboot)  
else:
   try: 
     API_ENDPOINT = config["api-endpoint"]
     API_TOKEN = config["api-token"]
     LOCALE = config["locale"]
     MIN = config["min"]
     MAX = config["max"]
     EMERGENCY_MIN = config["emergencyMin"]
     EMERGENCY_MAX = config["emergencyMax"] 
     TIMEZONE = "GMT" + config["timezone"]
     USE_BEEPER = config["beeper"]
     BEEPER_START_TIME = config["beeperStartTime"]
     BEEPER_END_TIME = config["beeperEndTime"]
     OLD_DATA = config["oldData"]
     OLD_DATA_EMERGENCY = config["oldDataEmergenc"]

     if MIN < 30: MIN=30
     if MAX < 100: MAX=100
     if EMERGENCY_MIN < 30 or MIN <= EMERGENCY_MIN: EMERGENCY_MIN=MIN-10
     if EMERGENCY_MAX < 100 or MAX >= EMERGENCY_MAX: EMERGENCY_MAX=MAX+10  
     if len(API_ENDPOINT) == 0: raise Exception("Empty api-endpoint parameter")
     if USE_BEEPER != 1 and USE_BEEPER != 0: USE_BEEPER=1
     if re.search("^GMT[+-]((0?[0-9]|1[0-1]):([0-5][0-9])|12:00)$",TIMEZONE) == None: TIMEZONE="GMT+0:00"
     if OLD_DATA < 10: OLD_DATA=10
     if OLD_DATA_EMERGENCY < 15: OLD_DATA_EMERGENCY=15

     timeStr = TIMEZONE[4:]
     [HH, MM] = [int(i) for i in timeStr.split(':')]
     secondsDiff = HH * 3600 + MM * 60
     if TIMEZONE[3] == "-": secondsDiff = secondsDiff * -1
     print('Setting local time seconds diff from UTC:', secondsDiff) 
   except Exception as e:
     sys.print_exception(e)
     saveError(e)
     config[ap.CONFIG] = 0
     ap.saveConfigFile(config)
     printCenteredText("Fix config!", mode, backgroundColor=M5.Display.COLOR.RED, clear=True)
     time.sleep(2)
     WDT(timeout=1000)
     shuttingDown = True
     printCenteredText("Restarting...", mode, backgroundColor=M5.Display.COLOR.RED, clear=True)

touchPadTimer = machine.Timer(0)
touchPadTimer.init(period=100, callback=touchPadCallback)

# from here code runs only if application is properly configured

try:
  nic = network.WLAN(network.STA_IF)
  nic.active(True)

  printCenteredText("Scanning wifi ...", mode, backgroundColor=M5.Display.COLOR.DARKGREY)

  wifi_password = None
  wifi_ssid = None  
  while wifi_password == None:
    try: 
      nets = nic.scan()
      for result in nets:
        wifi_ssid = result[0].decode() 
        if wifi_ssid in config: 
          wifi_password = config[wifi_ssid]
        else:
          print('No password for wifi ' + wifi_ssid + ' found')  
        if wifi_password != None: break
    except Exception as e:
      sys.print_exception(e)
      saveError(e)
      printCenteredText("Wifi not found!", mode, backgroundColor=M5.Display.COLOR.RED, clear=True)  
    if wifi_password == None: time.sleep(1)

  printCenteredText("Connecting wifi...", mode, backgroundColor=M5.Display.COLOR.DARKGREY) 
  nic.connect(wifi_ssid, wifi_password)
  print('Connecting wifi ' + wifi_ssid)
  while not nic.isconnected():
    print(".", end="")
    time.sleep(0.25)
  print("")  

  time_server = 'pool.ntp.org'
  printCenteredText("Setting time...", mode, backgroundColor=M5.Display.COLOR.DARKGREY) 
  print('Connecting time server ' + time_server)
  now_datetime = None
  while now_datetime is None:
    try:
      print(".", end="")
      #TODO use 0.pool.ntp.org, 1.pool.ntp.org, 2.pool.ntp.org, 3.pool.ntp.org
      ntptime.host = "pool.ntp.org" 
      ntptime.settime()
      now_datetime = getRtcDatetime()
      startTime = utime.time()
    except Exception as e:
      sys.print_exception(e)
      #saveError(e)
      time.sleep(2)
  print("\nCurrent UTC datetime " +  str(now_datetime))

  printCenteredText("Loading data...", mode, backgroundColor=M5.Display.COLOR.DARKGREY) 

  sgvDict = readSgvFile()
  dictLen = len(sgvDict)
  print("Loaded " + str(dictLen) + " sgv entries")

  #max 4 timers 0-3

  backendResponseTimer = machine.Timer(1)
  
  localtimeTimer = machine.Timer(2)
  localtimeTimer.init(period=1000, callback=localtimeCallback)

  accelTimer = machine.Timer(3)
  accelTimer.init(period=500, callback=accelCallback)

  #main method and threads

  _thread.start_new_thread(emergencyMonitor, ())
  _thread.start_new_thread(backendMonitor, ())
except Exception as e:
  sys.print_exception(e)
  #saveError(e)
  printCenteredText("Fix config!", mode, backgroundColor=M5.Display.COLOR.RED, clear=True)