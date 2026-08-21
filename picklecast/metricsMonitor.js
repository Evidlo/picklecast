async function metricsMonitor(pcFunction, pcType, delay) {

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
		let metric;
		
		// Standard
		if (report.type === 'transport' && report.selectedCandidatePairId) {
                    metric=`${pcType}_bytes_sent=${report.bytesSent}`;
		    console.log(metric);
                    metric=`${pcType}_bytes_recv=${report.bytesReceived}`;
		    console.log(metric);
		}
		
		// Firefox
		if (report.type === 'candidate-pair' && report.selected) {
                    metric=`${pcType}_bytes_sent=${report.bytesSent}`;
		    console.log(metric);
                    metric=`${pcType}_bytes_recv=${report.bytesReceived}`;
		    console.log(metric);
		}
		
		// All?
		if (report.type === 'remote-inbound-rtp') {
                    metric=`${pcType}_rtt_s=${report.roundTripTime}`;
		    console.log(metric);
                    metric=`${pcType}_packets_lost=${report.packetsLost}`;
		    console.log(metric);
		    metric=`${pcType}_jitter=${report.jitter}`;
		    console.log(metric);
		}
            });
	}
    } catch (err) {
	console.error("Getting metrics failed:".err);
    } finally {
	// Schedule next run after this one completes
	setTimeout(metricsMonitor, delay, pcFunction, pcType, delay);
    }
}

