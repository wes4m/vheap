/*
 *
 * Handle extensions here
 * Some examples already implemented below
 *
 * globalChunks struct can be accessed. modified. and attributes added as needed to globalChunks[chunkindex].extended
 * check github docs for more info
*/



 
function onCreateEdgeFromHeadToChunkNext(globalHeads, globalChunks, head, chunkIndex) {
	// To do: .. 
	// ex: checking if head loops
}

function onCreateEdgeFromChunkToChunkInit(globalChunks, currentChunkIndex) {
	// To do: ..
	// ex: check for double frees
	
	doubleFreeCheck(globalChunks, currentChunkIndex);
}

function onCreateEdgeFromChunkToChunkNext(globalChunks, currentChunkIndex, checkChunkIndex) {
	// To do: ..
	// ex: check for overalps, intersections between two chunks
	
	overlaps(globalChunks, currentChunkIndex, checkChunkIndex);
}






// Exts.
const redColor	   = "#d02d2d";
const darkRedColor = "#7e1e1e";
/*
* Check for overlaps/intersections skeletion.. # needs a lot of work 
*/
function overlaps(globalChunks, i, j) {
	// Check for intersections/overlaps *** needs more work, currently only applies to tcache/fastbins AKA fd ptr only //
	// Also need to check for currentChunk.chunkSize because it can go forwared to reach some chunk
	var currentChunk = globalChunks[i];
	var checkChunk   = globalChunks[j];
	if(hInt(currentChunk.fd) > hInt(checkChunk.address) && hInt(currentChunk.fd) < (hInt(checkChunk.address) + hInt(checkChunk.chunkSize))) {
		globalChunks[i].extended.rows.push({ "text": `Possible overlap, fd points inside chunk ${checkChunk.bin}[${checkChunk.index}]`, "color": redColor});
		globalChunks[i].extended.backgroundColor = darkRedColor;
	}
}

/*
* Checks if a chunk fd ptr loops over itself for double free possibility
*/
function doubleFreeCheck(globalChunks, i) {
	// Doulbe free / infinte loop bug
        var chunk = globalChunks[i];
	if(chunk.fd == chunk.address) {
		globalChunks[i].extended.rows.push({"text": "Infinite loop, Possibly double free", "color": redColor});
		globalChunks[i].extended.backgroundColor = darkRedColor;
        }	
}


/*
* hInt: Converts a hex string format [ 0xNNNN ] to js int
*/
function hInt(hexstr) {
        return parseInt(hexstr.replace("0x", ''), 16);
}

