from aiohttp import web
import threading
import asyncio
import socketio
import json
import sys

# GLOBALS #
loop         = None    # Thread loop
sio          = None    # Socket io
serving      = False   # To hold status of server
binsheads    = {}      # To hold bins heads
binschunks   = {}      # To hold bins chunks
vPath        = ""      # To hold viewsPath
# Defaults
gport        = 8080
ghost        = "localhost"



'''
    HTTP Server handler: handlers page, and js files requests
'''
def aiohttp_server():
    global sio, app

    sio = socketio.AsyncServer()

    def index(request):
        with open('{}vheap.html'.format(vPath)) as f:
            return web.Response(text=f.read(), content_type='text/html')

    def jsfile(request):
        global ghost, gport

        with open('{}static/js/'.format(vPath) + request.match_info['name']) as f:
            # Fixes JS files GHOST, GPORT before returning (To avoid CORS errors)
            return web.Response(text=f.read().replace("GHOST", ghost).replace("GPORT",gport),
                                content_type='text/javascript');

    '''
    on connect: do nothing
    '''
    @sio.on('connect')
    async def connected(sid, msg):
        pass

    '''
    on getHeap: send heap data to client
    '''
    @sio.on('getHeap')
    async def getHeap(sid, msg):
        await sio.emit("heapData", vheap_makeHeapData())

    # Create http server, and socket io
    app = web.Application()
    sio.attach(app)

    # router
    app.router.add_get('/', index)
    app.router.add_get(r'/static/js/{name}', jsfile)

    handler = web.AppRunner(app)

    return handler


'''
 Http Server thread runner
'''
def vheap_serve_thread(handler):
    global serving, ghost, gport, loop

    if serving:
        return

    # gdb does stupid shit sometimes have to do this
    if str(ghost) == "None" or str(gport) is "None":
        ghost = "localhost"
        gport = 8080


    serving = True
    print("vHeap is now serving on http://" + ghost + ":" + str(gport))

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(handler.setup())
    site = web.TCPSite(handler, ghost, gport)
    loop.run_until_complete(site.start())
    loop.run_forever()


'''
  Starts serving vHeap thread
'''
def vheap_serve(host="localhost", port=8080):
    global serving, ghost, gport, viewPath

    if not serving:
        ghost = host
        gport = port

        t = threading.Thread(target=vheap_serve_thread, args=(aiohttp_server(),))
        t.start()

'''
 Stops serving vHeap thread
'''
def vheap_stop():
    global loop

    if serving:
        loop.call_soon_threadsafe(loop.stop)

'''
 Clears the heap heads, bins
'''
def vheap_clearHeap():
    global binsheads, binschunks

    binsheads = {}
    binschunks = {}

'''
 Adds a bin head to heads dict wtih its value
'''
def vheap_addBinHead(head, address):
    global binsheads
    binsheads[head] = address

'''
 Adds a chunks to a specific bin
'''
def vheap_addChunkToBin(bin, chunk):
    global binschunks

    if not bin in binschunks:
        binschunks[bin] = []

    binschunks[bin].append(chunk)

'''
 Combines heads with bins as json text, ready to be sent to client
'''
def vheap_makeHeapData():
    global binsheads, binschunks

    ret = { "heads": binsheads, "bins": binschunks }
    return json.dumps(ret)

'''
 Makes a chunk struct
'''
def vheap_makeChunk(index, address, prevSize, chunkSize, a, m, p, fd, bk, allocated):
    chunk = {
             "index": index,
             "address": address,
             "prevSize": prevSize,
             "chunkSize": chunkSize,
             "a": a,
             "m": m,
             "p": p,
             "fd": fd,
             "bk": bk,
             "allocated": allocated
             }

    return chunk


# Init welcome #
vPath = __file__.replace("vheap.py","vheapViews/");

vheap_clearHeap()
vheap_addBinHead("vHeap is ready", "0x200");


