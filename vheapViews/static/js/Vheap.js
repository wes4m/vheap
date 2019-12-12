/*************************************************************************
 * Vheap.js, Main class. 
 * handles data
 */

/* GLOBAL */
hchunks   = null; // All current heap chunks
binsheads = null; // All current heap bins heads

function ChunkStruct(bin, index, address, prevSize, chunkSize, a, m, p, fd, bk, allocated) {
	this.bin = bin;
	this.index = index;
	this.address = address;
	this.prevSize = prevSize;
	this.chunkSize = chunkSize;
	this.a = a;
	this.m = m;
	this.p = p;
	this.fd = fd;
	this.bk = bk;

	this.allocated = allocated;
	this.extended = {"rows": [], "backgroundColor": ""};
}

/*
* InitHeap: Initalizer. 
* handles converting json to chunks struct, initializing the bins heads, and the chunks
*/
function InitHeap(jsonChunks) {
	binsheads = {};
	hchunks = [];

	var jdata = JSON.parse(jsonChunks);
	
	var heads = jdata["heads"];
	
	// Init bins heads
	for(var head in heads) {
		binsheads[head] = heads[head];
	}


	 var bins = jdata["bins"];
	 for(var bin in bins) {
		 for(i = 0; i < bins[bin].length; i++) {
			 var jchunk = bins[bin][i];
			 var chunk = new ChunkStruct(
				 bin,
				 jchunk.index,
				 jchunk.address,
				 jchunk.prevSize,
				 jchunk.chunkSize,
				 jchunk.a,
			         jchunk.m,
				 jchunk.p,
				 jchunk.fd,
				 jchunk.bk,
				 jchunk.allocated
			 );

			 hchunks.push(chunk);
		 }
	 }
}




/*
* makeHeadsDot: Generates the bins heads d3js-graphviz dot text. 
*/
function makeHeadsDot() {	
	var hdot = "\n// Heads \n"; 
	
	hdot +=`
		heads [
			shape = none;
			fontcolor=white;
			label=<<table border="0" color="#4c505c" bgcolor="#1b1e25" cellspacing="0">
              `;	

	for(head in binsheads) {
		hdot += `
			<tr border="0">
				<td port="${head}" border="1"><font color="#e49f33">${head}[]</font>: ${binsheads[head]} </td>
			</tr>` + "\n"; 
	}

	hdot += "</table>>];\n";
	return hdot;
}


/*
* makeBinDot: Generates a bin with its chunks d3js-graphviz dot text. 
*/
function makeBinDot(bin) {

	var binChunks = getBinChunks(bin);
	if(binChunks.length < 0) { return; }


	// bit colors for A,M,P flags
	bcolors = ["#d02d2d", "#44cc54"];
	backgroundColor = "#1b1e25";

	var cdot = "//" + bin + " chunks\n";
	for(i = 0; i < binChunks.length; i++) {
		var chunk = binChunks[i];

		// handle chunk background color set
		if(chunk.extended.backgroundColor != "") {
			backgroundColor = chunk.extended.backgroundColor;
		} else {
			backgroundColor = "#1b1e25"; // Default
		}

		cdot +=  
        	   `
			${bin}_${chunk.index} [    
			    shape = none;
			    fontcolor=white;
			    
			    label=<<table color="#4c505c" bgcolor="${backgroundColor}" border="0" cellspacing="0">
			    
			    <tr border="0">
			    	<td colspan="4" bgcolor="#0b0d0e" border="1"><font color="#e49f33">${bin}[${chunk.index}]</font>: ${chunk.address} </td>
			    </tr>
			    <tr border="0">
			    	<td port="prevSize" colspan="4" border="1">${chunk.prevSize}</td>
			    </tr>
			    <tr border="0">
			    	<td border="1">${chunk.chunkSize}</td>
				<td border="1"><font color="${bcolors[chunk.a]}">A(${chunk.a})</font></td>
				<td border="1"><font color="${bcolors[chunk.m]}">M(${chunk.m})</font></td>
				<td border="1"><font color="${bcolors[chunk.p]}">P(${chunk.p})</font></td>
			    </tr>
			    <tr border="0">
			    	<td port="fdPtr" colspan="4" border="1">${chunk.fd}</td>
			    </tr>
			    <tr border="0">
			    	<td port="bkPtr" colspan="4" border="1">${chunk.bk}</td>
			    </tr>
			    <tr border="0">
			    	<td port="data" colspan="4" border="1">.....</td>
			    </tr>
	        `;
		

		// Handle extensions
		for(c = 0; c < chunk.extended.rows.length; c++) {
			var ecolor = chunk.extended.rows[c]["color"];
			var etext  = chunk.extended.rows[c]["text"];

			cdot += `                           
			    <tr border="0">
			    	<td colspan="4" bgcolor="#0b0d0e" border="1"><font color="${ecolor}">${etext}</font> </td>
			    </tr>` + "\n";
		}

		cdot += 
		`
			</table>>
          		];
		`;

	}

	return cdot;
}


/*
* makeChunksEdgesDot: Generates the edges between chunks and heads, etc .. d3js-graphviz dot text. 
*/
function makeChunksEdgesDot() {

	var edges = "\n// Edges \n";


	// heads to chunks
	for(var head in binsheads) {
		for(k = 0; k < hchunks.length; k++) {
			var checkChunk = hchunks[k];

			// Only tcache bins point right back at the chunk data space where fd/bk are
			// other bins point at prevSize (real begining of chunk)

			pointAt = "prevSize";
			if(checkChunk.bin.includes("tcache")) {
				pointAt = "fdPtr";
			}

			// Handle heads to chunks extensions next
			onCreateEdgeFromHeadToChunkNext(binsheads, hchunks, head, k);

			if (binsheads[head] == checkChunk.address) {
				edges += `heads:${head} -> ${checkChunk.bin}_${checkChunk.index}:${pointAt}` + "\n";
			}
		}
	}

	// Chunks to chunks	
	for(i = 0; i < hchunks.length; i++) {
		
		var currentChunk = hchunks[i];
		
		// Handle chunks to chunks extensions init
		onCreateEdgeFromChunkToChunkInit(hchunks, i);

		// Check against other chunks	
		for(j = 0; j < hchunks.length; j++) {	
			var checkChunk = hchunks[j];
			
			// Handle chunk to chunk extensions next
			onCreateEdgeFromChunkToChunkNext(hchunks, i, j);

			// Regular edge fd/bk
			// Only tcache bins point right back at the chunk data space where fd/bk are
			// other bins point at prevSize (real begining of chunk)
		
			pointAt = "prevSize";
			if(currentChunk.bin.includes("tcache")) {
				pointAt = "fdPtr";
			}

			if(currentChunk.fd == checkChunk.address) {
				edges += `${currentChunk.bin}_${currentChunk.index}:fdPtr -> ${checkChunk.bin}_${checkChunk.index}:${pointAt}` + "\n";
			}
			
			if(currentChunk.bk == checkChunk.address) {
				edges += `${currentChunk.bin}_${currentChunk.index}:bkPtr -> ${checkChunk.bin}_${checkChunk.index}:${pointAt}` + "\n";
			}
				
			
		}
	
	}	

	return edges;	
}


/*
* getChunksDot: Responsible for collecting all dot generatos onto full layout.
* Also handles general layout styling 
*/
function getChunksDot()  {

	var dot = "digraph bins {";

	var layoutDot = 
	`
	    edge [color="#9297a9"];		// edge color
	    graph [bgcolor="#0b0d0e"];  // svg background color
	    newrank = true;		// Same level rows
	    nodesep = 0.2;		// Spacing between chunks
	    rankdir=LR;			// Left to right (horizontal) orientation
	`;		


	var headsDot = makeHeadsDot();
	var edges = makeChunksEdgesDot();

	// Get binDot for each non empty bin head
	var chunksDots = "";
	for(var head in binsheads) {
		chunksDots += makeBinDot(head.replace("head", ""));
	}


	dot += layoutDot + "\n";
	dot += headsDot + "\n";
	dot += chunksDots + "\n";
	dot += edges + "\n";
	dot += "}";

	return [[dot]];
}


/*
* getBinChunks: returns array of chunks in given bin
*/
function getBinChunks(bin) {
	var ret = [];
	for(i = 0; i < hchunks.length; i++) {
		var chunk = hchunks[i];
		if(chunk.bin == bin) {
			ret.push(chunk);
		}
	}

	return ret;
}

