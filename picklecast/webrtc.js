// var localVideo;
var localStream;
var remoteVideo;
var peerConnection;
var uuid;
var serverConnection;
var displayIP;

var peerConnectionConfig = {
  'iceServers': [
    {'urls': 'stun:stun.stunprotocol.org:3478'},
    {'urls': 'stun:stun.l.google.com:19302'},
  ]
};

function pageReady() {
  uuid = createUUID();

  // localVideo = document.getElementById('localVideo');
  remoteVideo = document.getElementById('remoteVideo');
  displayGUI = document.getElementById('displayGUI');
  displayIPs = Array.from(document.getElementsByClassName("displayIP"));
  displayVersion = document.getElementById("displayVersion")

  serverConnection = new WebSocket('wss://' + window.location.hostname + ':8443');
  serverConnection.onmessage = gotMessageFromServer;
}

function getUserMediaSuccess(stream) {
  localStream = stream;
  peerConnection.addStream(localStream);
  peerConnection.createOffer().then(createdDescription).catch(errorHandler);
  // localVideo.srcObject = stream;
}

function startScreenshare() {
  peerConnection = new RTCPeerConnection(peerConnectionConfig);
  peerConnection.onicecandidate = gotIceCandidate;

  var constraints = {
    video: {
      cursor: "always"
    },
    audio: false
  };
  if(navigator.mediaDevices.getDisplayMedia) {
    navigator.mediaDevices.getDisplayMedia(constraints).then(getUserMediaSuccess).catch(errorHandler);
  } else {
    alert('Your browser does not support getDisplayMedia API');
  }
}

function openWebRTCConnection() {
  peerConnection = new RTCPeerConnection(peerConnectionConfig);
  peerConnection.onicecandidate = gotIceCandidate;
  peerConnection.ontrack = gotRemoteStream;
  peerConnection.onconnectionstatechange = connectionStateChange;
}

// websocket message received from backend
function gotMessageFromServer(message) {
  if(!peerConnection) openWebRTCConnection();


  var signal = JSON.parse(message.data);
  // if message is from backend server
  if (signal.sender == "server") {
    displayIPs.forEach(
      function(el, ind, arr) {
        el.textContent = signal.message.address;
      }
    )
    displayVersion.textContent = signal.message.version;
    return
  }

  // if message if from another browser
  else if (signal.sender == "client") {
    // Ignore messages from ourself
    if(signal.message.uuid == uuid) return;

    if(signal.message.sdp) {
      peerConnection.setRemoteDescription(new RTCSessionDescription(signal.message.sdp)).then(function() {
        // Only create answers in response to offers
        if(signal.message.sdp.type == 'offer') {
          peerConnection.createAnswer().then(createdDescription).catch(errorHandler);
        }
      }).catch(errorHandler);
    } else if(signal.message.ice) {
      peerConnection.addIceCandidate(new RTCIceCandidate(signal.message.ice)).catch(errorHandler);
    }
  }

}

function gotIceCandidate(event) {
  if(event.candidate != null) {
    serverConnection.send(JSON.stringify({'ice': event.candidate, 'uuid': uuid}));
  }
}

function createdDescription(description) {
  peerConnection.setLocalDescription(description).then(function() {
    serverConnection.send(JSON.stringify({'sdp': peerConnection.localDescription, 'uuid': uuid}));
  }).catch(errorHandler);
}

function gotRemoteStream(event) {
  console.log('Got remote stream');
  // hide gui, show video
  displayGUI.style.display = 'none';
  remoteVideo.style.display = 'block';

  remoteVideo.srcObject = event.streams[0];
}

// websocket state change callback
function connectionStateChange(event) {
    switch(peerConnection.connectionState) {
    case "new":
    case "checking":
      console.log("Connecting...");
      break;
    case "connected":
      console.log("Online");
      break;
    case "disconnected":
      console.log("Disconnecting...");
      // show gui, hide video
      // displayGUI.style.display = 'flex';
      // remoteVideo.style.display = 'none';
      window.location.reload();
      break;
    case "closed":
      console.log("Offline");
      break;
    case "failed":
      console.log("Error");
      break;
    // default:
    //   console.log("Unknown");
    //   break;
  }
}

function errorHandler(error) {
  console.log(error);
}

// Taken from http://stackoverflow.com/a/105074/515584
// Strictly speaking, it's not a real UUID, but it gets the job done here
function createUUID() {
  function s4() {
    return Math.floor((1 + Math.random()) * 0x10000).toString(16).substring(1);
  }

  return s4() + s4() + '-' + s4() + '-' + s4() + '-' + s4() + '-' + s4() + s4() + s4();
}
