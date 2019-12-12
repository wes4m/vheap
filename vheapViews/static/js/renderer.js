/*************************************************************************
* renderer.js, handles rendering the page, connections.
*/

/* GLOBAL */ 
var chunkIndex 		= null;	   // To hold DOT src index for rendering
var chunks		= null;    // To hold acutal DOT text after generating
var graphviz 		= null;	   // graphviz renderer
var heapDataChunks 	= "";	   // To hold current heap data 
var oldHeapDataChunks 	= "diff";  // To hold previous heap data
var interval 		= null;    // To hold heapData reciver timed thread
/* 
* Socket IO handling 
* GHOST & GPORT are replaced by vheap.py during rumtime to avoid CORS errors.
*/
var socket = io('http://GHOST:GPORT');

/*
* on heapData: recives heap data from client and checks if there is any changes, then passes to Init to re-render the page.
* Recives heap data as json text.
*/
socket.on('heapData', function(data) {
	console.log("got heap data, re-rendering vheap");
	heapDataChunks = data;
	if(heapDataChunks != oldHeapDataChunks) {
		oldHeapDataChunks = heapDataChunks;
		Init();
	}
});


/*
* on connect: handles new connection, starts new timed interval for requesting heap data every 1 sec
*/
socket.on("connect", function() {
	console.log("connected");
	interval = setInterval(function() {
		socket.emit("getHeap", "");
	}, 1000);
});

/*
* on disconnect: handles disconnecting, stops timed interval.
*/
socket.on("disconnect", function() {
	console.log("disconnected");
	if(interval != null) {
		clearInterval(interval);
	}
});



/*
* Init: Starting point. main point for rendering. inits heap and requests DOT text, sets graph attributes then calls render func. 
*/
function Init() {
    chunkIndex = 0;
    chunks = [];

    // Only render if there is chunks in heap
    if(heapDataChunks.length > 0) {
    	
	// Pass json data to heap initalizer
	InitHeap(heapDataChunks);

	// Generates Dots
    	chunks = getChunksDot();

        // Set graph layout
        graphviz = d3.select("#graph").graphviz()
           .attributer(attributer);

    	// Start render process
	render();
    }
}



/*
* Renders the DOT text
*/
function render() {
    if(chunks.length <= 0) { return; }

    var chunksLines = chunks[chunkIndex];
    var chunk = chunksLines.join('');
 
    // Only renderes last DOT src
    graphviz
        .renderDot(chunk)
        .on("end", function () {
        chunkIndex += 1;
            if (chunkIndex < chunks.length) {
        	render();
            }
        });
}


/* 
* Handle svg styling/size.
* To makesure it fits the full page. 
*/
function attributer(datum, index, nodes) {
    var selection = d3.select(this);
    if (datum.tag == "svg") {
        var width  = window.innerWidth;  
        var height = window.innerHeight;
        var unit = 'px';
        selection
            .attr("width", width + unit)
            .attr("height", height + unit)
        datum.attributes.width = width + unit;
        datum.attributes.height = height + unit;
    }
}

/* 
* Handle window resizing
* re-render on resize
*/ 
$(window).bind("resize", function(){
    Init();
});

    
