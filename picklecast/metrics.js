// Monitor the metrics
async function metricsMonitor(pcFunction, pcType, delay) {

    // Get the latest peer connection
    pc = pcFunction();
    
    try {
	// Debugging to make sure its running
	// console.log('Checking for metrics');
    
	if ( pc != null) {

	    // Get the web rtc stats
            const stats = await pc.getStats();

	    // Lines to hold text to send
	    const metricArray = [];

	    // Loop through the different stats
            stats.forEach(report => {
		
		// See all possible reports
		// console.log(report.type);

		// Standard
		if (report.type === 'transport' && report.selectedCandidatePairId) {
		    {
			let metric = {};
			metric['name']=`tb_${pcType}_sent`;
			metric['prom_name']=`transported_bytes{endpoint="${pcType}",type="sent"}`;
			metric['value']=report.bytesSent;
			metric['desc']='WebRTC Data Transported';
			metricArray.push(metric);
		    }

		    {
			let metric = {};
			metric['name']=`tb_${pcType}_recv`;
			metric['prom_name']=`transported_bytes{endpoint="${pcType}",type="recv"}`;
			metric['value']=report.bytesReceived;
			metric['desc']='WebRTC Data Transported';
			metricArray.push(metric);
		    }
		}
		
		// Firefox
		if (report.type === 'candidate-pair' && report.selected) {

		    {
			let metric = {};
			metric['name']=`tb_${pcType}_send`;
			metric['prom_name']=`transported_bytes{endpoint="${pcType}",type="sent"}`;
			metric['value']=report.bytesSent;
			metric['desc']='WebRTC Data Transported';
			metricArray.push(metric);
		    }

		    {
			let metric = {}
			metric['name']=`tb_${pcType}_recv`;
			metric['prom_name']=`transported_bytes{endpoint="${pcType}",type="recv"}`;
			metric['value']=report.bytesReceived;
			metric['desc']='WebRTC Data Transported';
			metricArray.push(metric);
		    }
		}
		
		// All?
		if (report.type === 'remote-inbound-rtp') {
		    {
			let metric = {};
			metric['name']='rtt';
			metric['prom_name']=`${pcType}_rtt`;
			metric['value']=report.roundTripTime;
			metric['desc']='Round Trip Time (s)';
			metricArray.push(metric);
		    }
		    
		    {
			let metric = {};
			metric['name']='pkt_lost';
			metric['prom_name']=`${pcType}_packets_lost`;
			metric['value']=report.packetsLost;
			metric['desc']='Packets Lost';
			metricArray.push(metric);
		    }
			
		    {
			let metric = {};
			metric['name']='jit';
			metric['prom_name']=`${pcType}_jitter`;
			metric['value']=report.jitter;
			metric['desc']='Jitter';
			metricArray.push(metric);
		    }
		}

            });

	    // Create the data to post
	    let PostData = {};
	    PostData['secret'] = "secret";
	    PostData['data'] = metricArray;
	    
	    // Send the data
	    pushMetrics(pcType, PostData);
	    
	}
	
    } catch (err) {
	console.error("Getting metrics failed:".err);
	
    } finally {
	// Schedule next run after this one completes
	setTimeout(metricsMonitor, delay, pcFunction, pcType, delay);
    }
}

// Push metrics back to the server
async function pushMetrics(pcType, PostData) {

    let server = window.location.origin;
    let url = new URL(server);
    url.pathname = `/post/${pcType}`;

    // Convert to string
    let PostDataString = JSON.stringify(PostData);
    
    // Payload must be subtype text/plain
    const res = await fetch(url.toString(), {
	method: 'POST',
	headers: { 'Content-Type': 'application/json' },
	body: PostDataString,
    });
    
    if (!res.ok) {
	const txt = await res.text();
	throw new Error(`Metrics upload failed: ${res.status} ${txt}`);
    }
    console.log('Metrics successfully uploaded');
}
