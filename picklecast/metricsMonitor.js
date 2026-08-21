async function metricsMonitor(pcFunction, delay) {

    // Get the latest peer connection
    pc = pcFunction();
    
    try {
	// Debugging to make sure its running
	// console.log('Checking for metrics');
    
	if ( pc != null) {

	    // Get the web rtc stats
            const stats = await pc.getStats();

	    // Loop through the different stats
            stats.forEach(report => {
		
		// See all possible reports
		// console.log(report.type);
		
		// Standard
		if (report.type === 'transport' && report.selectedCandidatePairId) {
                    console.log('Bytes sent:', report.bytesSent);
                    console.log('Bytes received:', report.bytesReceived);
		}
		
		// Firefox
		if (report.type === 'candidate-pair' && report.selected) {
                    console.log('Bytes sent:', report.bytesSent);
                    console.log('Bytes received:', report.bytesReceived);
		}
		
		// All?
		if (report.type === 'remote-inbound-rtp') {
                    console.log('RTT (s):', report.roundTripTime);
                    console.log('Packets Lost:', report.packetsLost);
                    console.log('Jitter:', report.jitter);
		}
            });
	}
    } catch (err) {
	console.error("Getting metrics failed:".err);
    } finally {
	// Schedule next run after this one completes
	setTimeout(metricsMonitor, delay, pcFunction, delay);
    }
}

