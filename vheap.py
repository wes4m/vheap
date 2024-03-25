import argparse
from collections import defaultdict
from pathlib import Path
from aiohttp import web
import threading
import asyncio
import socketio
import json
import os

# pwndbg command implementation #
import gdb
import pwndbg.commands
import pwndbg.glibc
import pwndbg.heap
from pwndbg.commands import CommandCategory
from pwndbg.heap.ptmalloc import (
    Bins,
    Chunk,
    GlibcMemoryAllocator,
)


def vhadd_allchunks() -> None:
    allocator = pwndbg.heap.current
    assert isinstance(allocator, GlibcMemoryAllocator)
    main_arena = allocator.main_arena
    if main_arena is None:
        return

    i = 0
    vheap.addBinHead("allchunkshead", "all")

    for i, chunk in enumerate(main_arena.active_heap):
        achunk = vheap.makeChunk(
            i,
            chunk.address,
            chunk.prev_size,
            chunk.real_size,
            chunk.non_main_arena,
            chunk.is_mmapped,
            chunk.prev_inuse,
            chunk.fd,
            chunk.bk,
        )

        vheap.addChunkToBin("allchunks", achunk)


def vhadd_bins(bins: Bins, bin_name: str, safe_linking: bool, addr_offset: int = 0) -> None:
    allocator = pwndbg.heap.current
    assert isinstance(allocator, GlibcMemoryAllocator)

    if bins is not None:
        offset_fd = allocator.chunk_key_offset("fd")
        for bi, size in enumerate(bins.bins):
            thebin = bins.bins[size]
            tbinhead = thebin.fd_chain[0]
            if tbinhead != 0 and size != "type":
                tbinName = f"{bin_name}head{bi}"
                vheap.addBinHead(tbinName, str(hex(tbinhead)))

                # loop through chunks in the bin
                for i in range(len(thebin.fd_chain) - 1):
                    chunk = Chunk(thebin.fd_chain[i] + addr_offset)
                    fd = chunk.fd ^ ((chunk.address + offset_fd) >> 12 if safe_linking else 0)
                    jsonchunk = vheap.makeChunk(
                        i,
                        thebin.fd_chain[i],
                        chunk.prev_size,
                        chunk.real_size,
                        chunk.non_main_arena,
                        chunk.is_mmapped,
                        chunk.prev_inuse,
                        fd,
                        chunk.bk,
                    )

                    vheap.addChunkToBin(tbinName.replace("head", ""), jsonchunk)


parser = argparse.ArgumentParser()
parser.description = "Stops vHeap server."


@pwndbg.commands.ArgparsedCommand(parser, category=CommandCategory.HEAP)
def vhstop():
    """
    Stops the vheap server
    """
    vheap.stop()


parser = argparse.ArgumentParser()
parser.description = "Shows the current state of the heap on vHeap page."
parser.add_argument("host", nargs="?", type=str, default="localhost", help="The host to serve.")
parser.add_argument("port", nargs="?", type=int, default=8080, help="The port.")
parser.add_argument("--no-auto-update", action="store_true", help="Don't auto update the heap state on every stop.")


@pwndbg.commands.ArgparsedCommand(parser, category=CommandCategory.HEAP)
def vhserv(host="localhost", port=8080, no_auto_update=False):
    """
    Generates the json of current heap state and sends to vheap server.
    """
    vheap.serve(host, port, not no_auto_update)
    # Update the heap state right away
    if isinstance(pwndbg.heap.current, GlibcMemoryAllocator):
        vhstate()


parser = argparse.ArgumentParser()
parser.description = "Updates the vHeap view."


@pwndbg.commands.ArgparsedCommand(parser, category=CommandCategory.HEAP)
@pwndbg.commands.OnlyWhenRunning
@pwndbg.commands.OnlyWithResolvedHeapSyms
@pwndbg.commands.OnlyWhenHeapIsInitialized
@pwndbg.commands.OnlyWhenUserspace
def vhstate():

    vheap.clearHeap()

    allocator = pwndbg.heap.current
    if not isinstance(allocator, GlibcMemoryAllocator):
        return
    safe_lnk = pwndbg.glibc.check_safe_linking()

    vhadd_bins(allocator.tcachebins(None), "tcachebins", safe_lnk, -16)
    vhadd_bins(allocator.fastbins(None), "fastbins", safe_lnk)
    vhadd_bins(allocator.unsortedbin(None), "unsortedbin", False)
    vhadd_bins(allocator.smallbins(None), "smallbins", False)
    vhadd_bins(allocator.largebins(None), "largebins", False)

    vhadd_allchunks()


# end pwndbg commands #


class VisualHeap:
    # Thread loop
    loop: asyncio.AbstractEventLoop | None = None
    # Socket io
    sio: socketio.AsyncServer | None = None
    site: web.TCPSite | None = None
    # To hold status of server
    serving = False
    # To hold bins head addresses
    binsheads: dict[str, str] = {}
    # To hold bins chunks
    binschunks: dict[str, list[dict[str, str]]] = defaultdict(list)
    viewPath = Path(__file__).parent / "vheapViews"
    # Defaults
    port = 8080
    host = "localhost"
    auto_update = False

    def __init__(self):
        self.clearHeap()
        self.addBinHead("vHeap is ready", "0x200")

    def aiohttp_server(self) -> web.AppRunner:
        """
        HTTP Server handler: handlers page, and js files requests
        """
        self.sio = socketio.AsyncServer()

        async def index(_request: web.Request) -> web.Response:
            with open(self.viewPath / 'vheap.html', "r", encoding="utf-8") as f:
                return web.Response(text=f.read(), content_type='text/html')

        async def jsfile(request: web.Request) -> web.Response:
            with open(self.viewPath / 'static' / 'js' / os.path.basename(request.match_info['name']), "r", encoding="utf-8") as f:
                # Fixes JS files GHOST, GPORT before returning (To avoid CORS errors)
                return web.Response(text=f.read().replace("GHOST", self.host).replace("GPORT", str(self.port)),
                                    content_type='text/javascript')

        @self.sio.on('getHeap')
        async def getHeap(_sid, _msg):
            """
            on getHeap: send heap data to client
            """
            await self.sio.emit("heapData", self.makeHeapData())

        # Create http server, and socket io
        app = web.Application()
        self.sio.attach(app)

        # router
        app.router.add_get('/', index)
        app.router.add_get(r'/static/js/{name}', jsfile)

        handler = web.AppRunner(app)

        return handler

    def serve_thread(self) -> None:
        """
        Http Server thread runner
        """
        if self.serving:
            return

        self.serving = True
        print(f"vHeap is now serving on http://{self.host}:{self.port}")

        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.apprunner.setup())
        site = web.TCPSite(self.apprunner, self.host, self.port)
        self.loop.run_until_complete(site.start())
        self.loop.run_forever()

    def serve(self, host: str = "localhost", port: int = 8080, auto_update: bool = True) -> None:
        """
        Starts serving vHeap thread
        """
        if not self.serving:
            self.host = host
            self.port = port
            self.auto_update = auto_update
            self.apprunner = self.aiohttp_server()

            t = threading.Thread(target=self.serve_thread)
            t.start()

            if auto_update:
                gdb.events.stop.connect(gdb_stop_handler)

    def stop_threadsafe(self):
        self.loop.stop()
        self.clearHeap()
        self.serving = False
        print("vHeap server stopped")

    def stop(self) -> None:
        """
        Stops serving vHeap thread
        """
        if self.serving:
            print("Stopping vHeap server")
            asyncio.run_coroutine_threadsafe(self.apprunner.cleanup(), self.loop)
            self.loop.call_soon_threadsafe(self.stop_threadsafe)
            if self.auto_update:
                gdb.events.stop.disconnect(gdb_stop_handler)

    def clearHeap(self):
        """
        Clears the heap heads, bins
        """
        self.binsheads = {}
        self.binschunks = defaultdict(list)

    def addBinHead(self, head: str, address: str):
        """
        Adds a bin head to heads dict wtih its value
        """
        self.binsheads[head] = address

    def addChunkToBin(self, bin: str, chunk: dict[str, str]):
        """
        Adds a chunks to a specific bin
        """
        self.binschunks[bin].append(chunk)

    def makeHeapData(self) -> str:
        """
        Combines heads with bins as json text, ready to be sent to client
        """
        ret = {"heads": self.binsheads, "bins": self.binschunks}
        return json.dumps(ret)

    def makeChunk(
        self,
        index: int,
        address: int,
        prevSize: int | None,
        chunkSize: int | None,
        a: bool,
        m: bool,
        p: bool,
        fd: int | None,
        bk: int | None,
    ) -> dict[str, str]:
        """
        Makes a chunk struct
        """
        chunk = {
            "index": str(index),
            "address": hex(address),
            "prevSize": hex(prevSize) if prevSize is not None else "None",
            "chunkSize": hex(chunkSize) if chunkSize is not None else "None",
            "a": str(int(a)),
            "m": str(int(m)),
            "p": str(int(p)),
            "fd": hex(fd) if fd is not None else "None",
            "bk": hex(bk) if bk is not None else "None",
        }

        return chunk


vheap = VisualHeap()


def gdb_stop_handler(_event):
    vhstate()


def gdb_exit_handler(_event):
    vheap.stop()


gdb.events.gdb_exiting.connect(gdb_exit_handler)
