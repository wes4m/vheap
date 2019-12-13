#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import argparse
import struct

import gdb
import six

import pwndbg.color.context as C
import pwndbg.color.memory as M
import pwndbg.commands
import pwndbg.typeinfo
from pwndbg.color import generateColorFunction
from pwndbg.color import message

from pwndbg.vheap import vheap

def read_chunk(addr):
    # in old versions of glibc, `mchunk_[prev_]size` was simply called `[prev_]size`
    # to support both versions, we change the new names to the old ones here so that
    # the rest of the code can deal with uniform names
    renames = {
        "mchunk_size": "size",
        "mchunk_prev_size": "prev_size",
    }
    val = pwndbg.typeinfo.read_gdbvalue("struct malloc_chunk", addr)
    return dict({ renames.get(key, key): int(val[key]) for key in val.type.keys() }, value=val)


def format_bin(bins, verbose=False, offset=None):
    main_heap = pwndbg.heap.current
    if offset is None:
        offset = main_heap.chunk_key_offset('fd')

    result = []
    bins_type = bins.pop('type')

    for size in bins:
        b = bins[size]
        count, is_chain_corrupted = None, False

        # fastbins consists of only single linked list
        if bins_type == 'fastbins':
            chain_fd = b
        # tcachebins consists of single linked list and entries count
        elif bins_type == 'tcachebins':
            chain_fd, count = b
        # normal bins consists of double linked list and may be corrupted (we can detect corruption)
        else:  # normal bin
            chain_fd, chain_bk, is_chain_corrupted = b

        if not verbose and (chain_fd == [0] and not count) and not is_chain_corrupted:
            continue

        if bins_type == 'tcachebins':
            limit = 8
            if count <= 7:
                limit = count + 1
            formatted_chain = pwndbg.chain.format(chain_fd[0], offset=offset, limit=limit)
        else:
            formatted_chain = pwndbg.chain.format(chain_fd[0], offset=offset)


        if isinstance(size, int):
            size = hex(size)

        if is_chain_corrupted:
            line = message.hint(size) + message.error(' [corrupted]') + '\n'
            line += message.hint('FD: ') + formatted_chain + '\n'
            line += message.hint('BK: ') + pwndbg.chain.format(chain_bk[0], offset=main_heap.chunk_key_offset('bk'))
        else:
            if count is not None:
                line = (message.hint(size) + message.hint(' [%3d]' % count) + ': ').ljust(13)
            else:
                line = (message.hint(size) + ': ').ljust(13)
            line += formatted_chain

        result.append(line)

    if not result:
        result.append(message.hint('empty'))

    return result


parser = argparse.ArgumentParser()
parser.description = "Prints out chunks starting from the address specified by `addr`."
parser.add_argument("addr", nargs="?", type=int, default=None, help="The address of the heap.")
@pwndbg.commands.ArgparsedCommand(parser)
@pwndbg.commands.OnlyWhenRunning
@pwndbg.commands.OnlyWithLibcDebugSyms
@pwndbg.commands.OnlyWhenHeapIsInitialized
def heap(addr=None):
    """
    Prints out chunks starting from the address specified by `addr`.
    """
    main_heap  = pwndbg.heap.current
    main_arena = main_heap.main_arena
    if main_arena is None:
        return

    page = main_heap.get_heap_boundaries(addr)
    if addr is None:
        addr = page.vaddr

    # Print out all chunks on the heap
    # TODO: Add an option to print out only free or allocated chunks

    # Check if there is an alignment at the start of the heap
    size_t = pwndbg.arch.ptrsize
    first_chunk_size = pwndbg.arch.unpack(pwndbg.memory.read(addr + size_t, size_t))
    if first_chunk_size == 0:
        addr += size_t * 2  # Skip the alignment

    while addr < page.vaddr + page.memsz:
        chunk = malloc_chunk(addr)  # Prints the chunk
        size = int(chunk['size'])

        # Clear the bottom 3 bits
        size &= ~7
        if size == 0:
            break
        addr += size

parser = argparse.ArgumentParser()
parser.description = "Prints out the main arena or the arena at the specified by address."
parser.add_argument("addr", nargs="?", type=int, default=None, help="The address of the arena.")
@pwndbg.commands.ArgparsedCommand(parser)
@pwndbg.commands.OnlyWhenRunning
@pwndbg.commands.OnlyWithLibcDebugSyms
@pwndbg.commands.OnlyWhenHeapIsInitialized
def arena(addr=None):
    """
    Prints out the main arena or the arena at the specified by address.
    """
    main_heap   = pwndbg.heap.current
    main_arena  = main_heap.get_arena(addr)

    if main_arena is None:
        return

    print(main_arena)


parser = argparse.ArgumentParser()
parser.description = "Prints out allocated arenas."
@pwndbg.commands.ArgparsedCommand(parser)
@pwndbg.commands.OnlyWhenRunning
@pwndbg.commands.OnlyWithLibcDebugSyms
@pwndbg.commands.OnlyWhenHeapIsInitialized
def arenas():
    """
    Prints out allocated arenas.
    """
    heap = pwndbg.heap.current
    for ar in heap.arenas:
        print(ar)


parser = argparse.ArgumentParser()
parser.description = "Print malloc thread cache info."
parser.add_argument("addr", nargs="?", type=int, default=None, help="The address of the tcache.")
@pwndbg.commands.ArgparsedCommand(parser)
@pwndbg.commands.OnlyWhenRunning
@pwndbg.commands.OnlyWithLibcDebugSyms
@pwndbg.commands.OnlyWhenHeapIsInitialized
def tcache(addr=None):
    """
    Prints out the thread cache.

    Glibc 2.26 malloc introduced per-thread chunk cache. This command prints
    out per-thread control structure of the cache.
    """
    main_heap = pwndbg.heap.current
    tcache = main_heap.get_tcache(addr)

    if tcache is None:
        return

    print(tcache)


parser = argparse.ArgumentParser()
parser.description = "Prints out the mp_ structure from glibc."
@pwndbg.commands.ArgparsedCommand(parser)
@pwndbg.commands.OnlyWhenRunning
@pwndbg.commands.OnlyWithLibcDebugSyms
@pwndbg.commands.OnlyWhenHeapIsInitialized
def mp():
    """
    Prints out the mp_ structure from glibc
    """
    main_heap   = pwndbg.heap.current

    print(main_heap.mp)


parser = argparse.ArgumentParser()
parser.description = "Prints out the address of the top chunk of the main arena, or of the arena at the specified address."
parser.add_argument("addr", nargs="?", type=int, default=None, help="The address of the arena.")
@pwndbg.commands.ArgparsedCommand(parser)
@pwndbg.commands.OnlyWhenRunning
@pwndbg.commands.OnlyWithLibcDebugSyms
@pwndbg.commands.OnlyWhenHeapIsInitialized
def top_chunk(addr=None):
    """
    Prints out the address of the top chunk of the main arena, or of the arena
    at the specified address.
    """
    main_heap   = pwndbg.heap.current
    main_arena  = main_heap.get_arena(addr)

    if main_arena is None:
        heap_region = main_heap.get_heap_boundaries()
        if not heap_region:
            print(message.error('Could not find the heap'))
            return

        heap_start = heap_region.vaddr
        heap_end   = heap_start + heap_region.size

        # If we don't know where the main_arena struct is, just iterate
        # through all the heap objects until we hit the last one
        last_addr = None
        addr = heap_start
        while addr < heap_end:
            chunk = read_chunk(addr)
            size = int(chunk['size'])

            # Clear the bottom 3 bits
            size &= ~7

            last_addr = addr
            addr += size
            addr += size
        address = last_addr
    else:
        address = main_arena['top']

    return malloc_chunk(address)




def getfdbk(chunk):
    c = read_chunk(chunk)
    return c["prev_size"], c["size"]



def vhadd_allchunks():

    addr = None

    main_heap  = pwndbg.heap.current
    main_arena = main_heap.main_arena
    if main_arena is None:
        return

    page = main_heap.get_heap_boundaries(addr)
    if addr is None:
        addr = page.vaddr

    # all chunks on the heap
    # Check if there is an alignment at the start of the heap
    size_t = pwndbg.arch.ptrsize
    first_chunk_size = pwndbg.arch.unpack(pwndbg.memory.read(addr + size_t, size_t))
    if first_chunk_size == 0:
        addr += size_t * 2  # Skip the alignment

    i = 0
    vheap.vheap_addBinHead("allchunkshead", "all")

    while addr < page.vaddr + page.memsz:
        chunk = read_chunk(addr)
        size = int(chunk['size'])
        prev_size = int(chunk['prev_size'])
        actual_size = size & ~7
        prev_inuse, is_mmapped, non_main_arena = main_heap.chunk_flags(size)
        fd, bk = getfdbk(addr)

        achunk = vheap.vheap_makeChunk(str(i),
                                       str(hex(addr)),
                                       str(hex(prev_size)),
                                       str(hex(actual_size)),
                                       str(non_main_arena),
                                       str(is_mmapped),
                                       str(prev_inuse),
                                       str(hex(fd)),
                                       str(hex(bk))
                                       )

        vheap.vheap_addChunkToBin("allchunks", achunk)

        # Clear the bottom 3 bits
        size &= ~7
        if size == 0:
            break
        addr += size
        i += 1



def vhadd_tcachebins():

    # TCAHCEBINS
    main_heap = pwndbg.heap.current
    tcachebins = main_heap.tcachebins(None)

    if tcachebins is not None:
        ti = 0
        for size in tcachebins:
            ti += 1
            tbin = tcachebins[size]
            tbinhead = tbin[0][0]
            if(tbinhead != 0 and size != "type"):
                tbinName = "tcachebinshead" + str(ti)
                vheap.vheap_addBinHead(tbinName, str(hex(tbinhead)))

                # loop through chunks in tbin
                for i in range(len(tbin[0])-1):
                    chunk = read_chunk(tbin[0][i]-16)
                    size = int(chunk['size'])
                    prev_size = int(chunk['prev_size'])
                    actual_size = size & ~7
                    prev_inuse, is_mmapped, non_main_arena = main_heap.chunk_flags(size)
                    fd, bk = getfdbk(tbin[0][i])

                    tchunk = vheap.vheap_makeChunk(str(i),
                                                   str(hex(tbin[0][i])),
                                                   str(hex(prev_size)),
                                                   str(hex(actual_size)),
                                                   str(non_main_arena),
                                                   str(is_mmapped),
                                                   str(prev_inuse),
                                                   str(hex(fd)),
                                                   str(hex(bk))
                                                   )

                    vheap.vheap_addChunkToBin(tbinName.replace("head", ""), tchunk)


def vhadd_fastbins():

    # FASTBINS
    main_heap = pwndbg.heap.current
    fastbins = main_heap.fastbins(None)

    if fastbins is not None:
        fi = 0
        for size in fastbins:
            fi += 1
            fbin = fastbins[size]
            fbinhead = fbin[0]
            if(fbinhead != 0 and size != "type"):
                fbinName = "fastbinshead" + str(fi)
                vheap.vheap_addBinHead(fbinName, str(hex(fbinhead)))

                # loop through chunks in fbin
                for i in range(len(fbin)-1):
                    chunk = read_chunk(fbin[i])
                    size = int(chunk['size'])
                    prev_size = int(chunk['prev_size'])
                    actual_size = size & ~7
                    prev_inuse, is_mmapped, non_main_arena = main_heap.chunk_flags(size)
                    fd, bk = getfdbk(fbin[i]+16)

                    fchunk = vheap.vheap_makeChunk(str(i),
                                                   str(hex(fbin[i])),
                                                   str(hex(prev_size)),
                                                   str(hex(actual_size)),
                                                   str(non_main_arena),
                                                   str(is_mmapped),
                                                   str(prev_inuse),
                                                   str(hex(fd)),
                                                   str(hex(bk))
                                                   )

                    vheap.vheap_addChunkToBin(fbinName.replace("head", ""), fchunk)


def vhadd_unsortedbin():

    # Unsortedbin
    main_heap = pwndbg.heap.current
    unsortedbin = main_heap.unsortedbin(None)


    if unsortedbin is not None:
        ui = 0
        for size in unsortedbin:
            ui += 1
            ubin = unsortedbin[size]
            ubinhead = ubin[0][0]  # FDs  / [1][] for BKs

            if(ubinhead != 0 and size != "type"):
                ubinName = "unsortedbinshead" + str(ui)
                vheap.vheap_addBinHead(ubinName, str(hex(ubinhead)))

                # loop through fd of chunks in ubin
                for i in range(len(ubin[0])-1):
                    chunk = read_chunk(ubin[0][i])
                    size = int(chunk['size'])
                    prev_size = int(chunk['prev_size'])
                    actual_size = size & ~7
                    prev_inuse, is_mmapped, non_main_arena = main_heap.chunk_flags(size)
                    fd, bk = getfdbk(ubin[0][i]+16)

                    uchunk = vheap.vheap_makeChunk(str(i),
                                                   str(hex(ubin[0][i])),
                                                   str(hex(prev_size)),
                                                   str(hex(actual_size)),
                                                   str(non_main_arena),
                                                   str(is_mmapped),
                                                   str(prev_inuse),
                                                   str(hex(fd)),
                                                   str(hex(bk))
                                                   )

                    vheap.vheap_addChunkToBin(ubinName.replace("head", ""), uchunk)



def vhadd_smallbins():

    # Unsortedbin
    main_heap = pwndbg.heap.current
    smallbins = main_heap.smallbins(None)


    if smallbins is not None:
        si = 0
        for size in smallbins:
            si += 1
            sbin = smallbins[size]
            sbinhead = sbin[0][0]  # FDs  / [1][] for BKs

            if(sbinhead != 0 and size != "type"):
                sbinName = "smallbinshead" + str(si)
                vheap.vheap_addBinHead(sbinName, str(hex(sbinhead)))

                # loop through fd of chunks in sbin
                for i in range(len(sbin[0])-1):
                    chunk = read_chunk(sbin[0][i])
                    size = int(chunk['size'])
                    prev_size = int(chunk['prev_size'])
                    actual_size = size & ~7
                    prev_inuse, is_mmapped, non_main_arena = main_heap.chunk_flags(size)
                    fd, bk = getfdbk(sbin[0][i]+16)

                    schunk = vheap.vheap_makeChunk(str(i),
                                                   str(hex(sbin[0][i])),
                                                   str(hex(prev_size)),
                                                   str(hex(actual_size)),
                                                   str(non_main_arena),
                                                   str(is_mmapped),
                                                   str(prev_inuse),
                                                   str(hex(fd)),
                                                   str(hex(bk))
                                                   )

                    vheap.vheap_addChunkToBin(sbinName.replace("head", ""), schunk)




def vhadd_largebins():

    # Unsortedbin
    main_heap = pwndbg.heap.current
    largebins = main_heap.largebins(None)


    if largebins is not None:
        li = 0
        for size in largebins:
            li += 1
            lbin = largebins[size]
            lbinhead = lbin[0][0]  # FDs  / [1][] for BKs

            if(lbinhead != 0 and size != "type"):
                lbinName = "largebinshead" + str(li)
                vheap.vheap_addBinHead(lbinName, str(hex(lbinhead)))

                # loop through fd of chunks in sbin
                for i in range(len(lbin[0])-1):
                    chunk = read_chunk(lbin[0][i])
                    size = int(chunk['size'])
                    prev_size = int(chunk['prev_size'])
                    actual_size = size & ~7
                    prev_inuse, is_mmapped, non_main_arena = main_heap.chunk_flags(size)
                    fd, bk = getfdbk(lbin[0][i]+16)

                    lchunk = vheap.vheap_makeChunk(str(i),
                                                   str(hex(lbin[0][i])),
                                                   str(hex(prev_size)),
                                                   str(hex(actual_size)),
                                                   str(non_main_arena),
                                                   str(is_mmapped),
                                                   str(prev_inuse),
                                                   str(hex(fd)),
                                                   str(hex(bk))
                                                   )

                    vheap.vheap_addChunkToBin(lbinName.replace("head", ""), lchunk)



parser = argparse.ArgumentParser()
parser.description = "Stops vHeap server."
@pwndbg.commands.ArgparsedCommand(parser)
def vhstop():
    """
    Stops the vheap server
    """
    vheap.vheap_stop()


parser = argparse.ArgumentParser()
parser.description = "Shows the current state of the heap on vHeap page."
parser.add_argument("host", nargs="?", type=str, default=None, help="The host to serve.")
parser.add_argument("port", nargs="?", type=int, default=None, help="The port.")


@pwndbg.commands.ArgparsedCommand(parser)
def vhserv(host="localhost", port=8080):
    """
    Generates the json of current heap state and sends to vheap server.
    """
    vheap.vheap_serve("{}".format(host), "{}".format(port))


parser = argparse.ArgumentParser()
parser.description = "Updates the vHeap view."
@pwndbg.commands.ArgparsedCommand(parser)
@pwndbg.commands.OnlyWhenRunning
@pwndbg.commands.OnlyWithLibcDebugSyms
@pwndbg.commands.OnlyWhenHeapIsInitialized
def vhstate():


    vheap.vheap_clearHeap()

    vhadd_tcachebins()
    vhadd_fastbins()

    vhadd_unsortedbin()

    vhadd_smallbins()
    vhadd_largebins()

    vhadd_allchunks()


parser = argparse.ArgumentParser()
parser.description = "Prints out the malloc_chunk at the specified address."
parser.add_argument("addr", nargs="?", type=int, default=None, help="The address of the chunk.")
parser.add_argument("fake", nargs="?", type=bool, default=False, help="If the chunk is a fake chunk.")#TODO describe this better
@pwndbg.commands.ArgparsedCommand(parser)
@pwndbg.commands.OnlyWhenRunning
@pwndbg.commands.OnlyWithLibcDebugSyms
@pwndbg.commands.OnlyWhenHeapIsInitialized
def malloc_chunk(addr,fake=False):
    """
    Prints out the malloc_chunk at the specified address.
    """
    main_heap = pwndbg.heap.current

    if not isinstance(addr, six.integer_types):
        addr = int(addr)

    chunk = read_chunk(addr)
    size = int(chunk['size'])
    actual_size = size & ~7
    prev_inuse, is_mmapped, non_main_arena = main_heap.chunk_flags(size)
    arena = None
    if not fake and non_main_arena:
        arena = main_heap.get_heap(addr)['ar_ptr']

    fastbins = [] if fake else main_heap.fastbins(arena)
    header = M.get(addr)
    if fake:
        header += message.prompt(' FAKE')
    if prev_inuse:
        if actual_size in fastbins:
            header += message.hint(' FASTBIN')
        else:
            header += message.hint(' PREV_INUSE')
    if is_mmapped:
        header += message.hint(' IS_MMAPED')
    if non_main_arena:
        header += message.hint(' NON_MAIN_ARENA')
    print(header, chunk["value"])

    return chunk


parser = argparse.ArgumentParser()
parser.description = """
    Prints out the contents of the tcachebins, fastbins, unsortedbin, smallbins, and largebins from the
    main_arena or the specified address.
    """
parser.add_argument("addr", nargs="?", type=int, default=None, help="The address of the bins.") #TODO describe this better if necessary
parser.add_argument("tcache_addr", nargs="?", type=int, default=None, help="The address of the tcache.")
@pwndbg.commands.ArgparsedCommand(parser)
@pwndbg.commands.OnlyWhenRunning
@pwndbg.commands.OnlyWithLibcDebugSyms
@pwndbg.commands.OnlyWhenHeapIsInitialized
def bins(addr=None, tcache_addr=None):
    """
    Prints out the contents of the tcachebins, fastbins, unsortedbin, smallbins, and largebins from the
    main_arena or the specified address.
    """
    if pwndbg.heap.current.has_tcache():
        tcachebins(tcache_addr)
    fastbins(addr)
    unsortedbin(addr)
    smallbins(addr)
    largebins(addr)


parser = argparse.ArgumentParser()
parser.description = """
    Prints out the contents of the fastbins of the main arena or the arena
    at the specified address.
    """
parser.add_argument("addr", nargs="?", type=int, default=None, help="The address of the fastbins.")
parser.add_argument("verbose", nargs="?", type=bool, default=True, help="Whether to show more details or not.")
@pwndbg.commands.ArgparsedCommand(parser)
@pwndbg.commands.OnlyWhenRunning
@pwndbg.commands.OnlyWithLibcDebugSyms
@pwndbg.commands.OnlyWhenHeapIsInitialized
def fastbins(addr=None, verbose=True):
    """
    Prints out the contents of the fastbins of the main arena or the arena
    at the specified address.
    """
    main_heap = pwndbg.heap.current
    fastbins  = main_heap.fastbins(addr)

    if fastbins is None:
        return

    formatted_bins = format_bin(fastbins, verbose)

    print(C.banner('fastbins'))
    for node in formatted_bins:
        print(node)


parser = argparse.ArgumentParser()
parser.description = """
    Prints out the contents of the unsorted bin of the main arena or the
    arena at the specified address.
    """
parser.add_argument("addr", nargs="?", type=int, default=None, help="The address of the unsorted bin.")
parser.add_argument("verbose", nargs="?", type=bool, default=True, help="Whether to show more details or not.")
@pwndbg.commands.ArgparsedCommand(parser)
@pwndbg.commands.OnlyWhenRunning
@pwndbg.commands.OnlyWithLibcDebugSyms
@pwndbg.commands.OnlyWhenHeapIsInitialized
def unsortedbin(addr=None, verbose=True):
    """
    Prints out the contents of the unsorted bin of the main arena or the
    arena at the specified address.
    """
    main_heap   = pwndbg.heap.current
    unsortedbin = main_heap.unsortedbin(addr)

    if unsortedbin is None:
        return

    formatted_bins = format_bin(unsortedbin, verbose)

    print(C.banner('unsortedbin'))
    for node in formatted_bins:
        print(node)


parser = argparse.ArgumentParser()
parser.description = """
    Prints out the contents of the small bin of the main arena or the arena
    at the specified address.
    """
parser.add_argument("addr", nargs="?", type=int, default=None, help="The address of the smallbins.")
parser.add_argument("verbose", nargs="?", type=bool, default=False, help="Whether to show more details or not.")
@pwndbg.commands.ArgparsedCommand(parser)
@pwndbg.commands.OnlyWhenRunning
@pwndbg.commands.OnlyWithLibcDebugSyms
@pwndbg.commands.OnlyWhenHeapIsInitialized
def smallbins(addr=None, verbose=False):
    """
    Prints out the contents of the small bin of the main arena or the arena
    at the specified address.
    """
    main_heap = pwndbg.heap.current
    smallbins = main_heap.smallbins(addr)

    if smallbins is None:
        return

    formatted_bins = format_bin(smallbins, verbose)

    print(C.banner('smallbins'))
    for node in formatted_bins:
        print(node)


parser = argparse.ArgumentParser()
parser.description = """
    Prints out the contents of the large bin of the main arena or the arena
    at the specified address.
    """
parser.add_argument("addr", nargs="?", type=int, default=None, help="The address of the largebins.")
parser.add_argument("verbose", nargs="?", type=bool, default=False, help="Whether to show more details or not.")
@pwndbg.commands.ArgparsedCommand(parser)
@pwndbg.commands.OnlyWhenRunning
@pwndbg.commands.OnlyWithLibcDebugSyms
@pwndbg.commands.OnlyWhenHeapIsInitialized
def largebins(addr=None, verbose=False):
    """
    Prints out the contents of the large bin of the main arena or the arena
    at the specified address.
    """
    main_heap = pwndbg.heap.current
    largebins = main_heap.largebins(addr)

    if largebins is None:
        return

    formatted_bins = format_bin(largebins, verbose)

    print(C.banner('largebins'))
    for node in formatted_bins:
        print(node)


parser = argparse.ArgumentParser()
parser.description = """
    Prints out the contents of the bins in current thread tcache or in tcache
    at the specified address.
    """
parser.add_argument("addr", nargs="?", type=int, default=None, help="The address of the tcache bins.")
parser.add_argument("verbose", nargs="?", type=bool, default=False, help="Whether to show more details or not.")
@pwndbg.commands.ArgparsedCommand(parser)
@pwndbg.commands.OnlyWhenRunning
@pwndbg.commands.OnlyWithLibcDebugSyms
@pwndbg.commands.OnlyWhenHeapIsInitialized
def tcachebins(addr=None, verbose=False):
    """
    Prints out the contents of the bins in current thread tcache or in tcache
    at the specified address.
    """
    main_heap = pwndbg.heap.current
    tcachebins = main_heap.tcachebins(addr)

    if tcachebins is None:
        return

    formatted_bins = format_bin(tcachebins, verbose, offset = main_heap.tcache_next_offset)

    print(C.banner('tcachebins'))
    for node in formatted_bins:
        print(node)


parser = argparse.ArgumentParser()
parser.description = """
    Finds candidate fake fast chunks that will overlap with the specified
    address. Used for fastbin dups and house of spirit
    """
parser.add_argument("addr", type=int, help="The start address.") #TODO describe these better
parser.add_argument("size", type=int, help="The size.")
@pwndbg.commands.ArgparsedCommand(parser)
@pwndbg.commands.OnlyWhenRunning
@pwndbg.commands.OnlyWithLibcDebugSyms
@pwndbg.commands.OnlyWhenHeapIsInitialized
def find_fake_fast(addr, size):
    """
    Finds candidate fake fast chunks that will overlap with the specified
    address. Used for fastbin dups and house of spirit
    """
    main_heap = pwndbg.heap.current
    max_fast = main_heap.global_max_fast
    fastbin  = main_heap.fastbin_index(int(size))
    start    = int(addr) - int(max_fast)
    mem      = pwndbg.memory.read(start, max_fast, partial=True)

    fmt = {
        'little': '<',
        'big': '>'
    }[pwndbg.arch.endian] + {
        4: 'I',
        8: 'Q'
    }[pwndbg.arch.ptrsize]

    print(C.banner("FAKE CHUNKS"))
    for offset in range(max_fast - pwndbg.arch.ptrsize):
        candidate = mem[offset:offset + pwndbg.arch.ptrsize]
        if len(candidate) == pwndbg.arch.ptrsize:
            value = struct.unpack(fmt, candidate)[0]

            if main_heap.fastbin_index(value) == fastbin:
                malloc_chunk(start+offset-pwndbg.arch.ptrsize,fake=True)


vis_heap_chunks_parser = argparse.ArgumentParser(description='Visualize heap chunks at the specified address')
vis_heap_chunks_parser.add_argument('count', nargs='?', default=10,
                    help='Number of chunks to visualize')
vis_heap_chunks_parser.add_argument('address', help='Start address', nargs='?', default=None)
vis_heap_chunks_parser.add_argument('--naive', '-n', help='Don\'t use end-of-heap heuristics', action='store_true', default=False)

@pwndbg.commands.ArgparsedCommand(vis_heap_chunks_parser)
@pwndbg.commands.OnlyWhenRunning
@pwndbg.commands.OnlyWithLibcDebugSyms
@pwndbg.commands.OnlyWhenHeapIsInitialized
def vis_heap_chunks(address=None, count=None, naive=None):
    address = int(address) if address else pwndbg.heap.current.get_heap_boundaries().vaddr
    main_heap = pwndbg.heap.current
    main_arena = main_heap.get_arena()
    top_chunk = int(main_arena['top'])

    unpack = pwndbg.arch.unpack

    cells_map = {}
    chunk_id = 0
    ptr_size = pwndbg.arch.ptrsize
    while chunk_id < count:
        prev_size = unpack(pwndbg.memory.read(address, ptr_size))
        current_size = unpack(pwndbg.memory.read(address+ptr_size, ptr_size))
        real_size = current_size & ~main_heap.malloc_align_mask
        prev_inuse = current_size & 1
        stop_addr = address + real_size

        while address < stop_addr and (naive or address < top_chunk):
            assert address not in cells_map
            cells_map[address] = chunk_id
            address += ptr_size

        if prev_inuse and (naive or address != top_chunk):
            cells_map[address - real_size] -= 1

        chunk_id += 1

        # we reached top chunk, add it's metadata and break
        if address >= top_chunk:
            cells_map[address] = chunk_id
            cells_map[address+ptr_size] = chunk_id
            break

    # TODO: maybe print free chunks in bold or underlined
    color_funcs = [
        generateColorFunction("yellow"),
        generateColorFunction("cyan"),
        generateColorFunction("purple"),
        generateColorFunction("green"),
        generateColorFunction("blue"),
    ]

    addrs = sorted(cells_map.keys())
    bin_collections = [
        pwndbg.heap.current.fastbins(None),
        pwndbg.heap.current.unsortedbin(None),
        pwndbg.heap.current.smallbins(None),
        pwndbg.heap.current.largebins(None),
        ]
    if pwndbg.heap.current.has_tcache():
        bin_collections.insert(0, pwndbg.heap.current.tcachebins(None))

    printed = 0
    out = ''
    asc = ''
    labels = []

    for addr in addrs:
        if printed % 2 == 0:
            out += "\n0x%x" % addr

        cell = unpack(pwndbg.memory.read(addr, ptr_size))
        cell_hex = '\t0x{:0{n}x}'.format(cell, n=ptr_size*2)

        chunk_idx = cells_map[addr]
        color_func_idx = chunk_idx % len(color_funcs)
        color_func = color_funcs[color_func_idx]

        out += color_func(cell_hex)
        printed += 1

        labels.extend(bin_labels(addr, bin_collections))
        if addr == top_chunk:
            labels.append('Top chunk')

        asc += bin_ascii(pwndbg.memory.read(addr, ptr_size))
        if printed % 2 == 0:
            out += '\t' + color_func(asc) + ('\t <-- ' + ', '.join(labels) if len(labels) else '')
            asc = ''
            labels = []

    print(out)

def bin_ascii(bs):
    from string import printable
    valid_chars = list(map(ord, set(printable) - set('\t\r\n')))
    return ''.join(chr(c) if c in valid_chars else '.'for c in bs)

def bin_labels(addr, collections):
    labels = []
    for bins in collections:
        bins_type = bins.get('type', None)
        if not bins_type:
            continue

        for size in filter(lambda x: x != 'type', bins.keys()):
            b = bins[size]
            if isinstance(size, int):
                size = hex(size)
            count = '/{:d}'.format(b[1]) if bins_type == 'tcachebins' else None
            chunks = bin_addrs(b, bins_type)
            for chunk_addr in chunks:
                if addr == chunk_addr:
                    labels.append('{:s}[{:s}][{:d}{}]'.format(bins_type, size, chunks.index(addr), count or ''))

    return labels

def bin_addrs(b, bins_type):
    addrs = []
    if bins_type == 'fastbins':
        return b
    # tcachebins consists of single linked list and entries count
    elif bins_type == 'tcachebins':
        addrs, _ = b
    # normal bins consists of double linked list and may be corrupted (we can detect corruption)
    else:  # normal bin
        addrs, _, _ = b
    return addrs
