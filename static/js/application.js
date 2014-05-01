var inbox = new ReconnectingWebSocket("ws://"+ location.host + "/receive");
var outbox = new ReconnectingWebSocket("ws://"+ location.host + "/submit");

var textShadow = "";
var dmp = new diff_match_patch();
var id = Math.floor(Math.random()*11);

inbox.onmessage = function(message) {
  var data = JSON.parse(message.data);
  // ignore own patch, else patch text and shadow
  if (data.id != id) {
    //console.log(data)
    var text  = $("#input-text")[0].value;
    var patches = dmp.patch_fromText(data.patch_text);
    var results = dmp.patch_apply(patches, text);
    shadowResults = dmp.patch_apply(patches, textShadow);
    textShadow = shadowResults[0];
    $("#input-text")[0].value = results[0];
  }
};

inbox.onclose = function(){
    console.log('inbox closed');
    this.inbox = new WebSocket(inbox.url);
};

outbox.onclose = function(){
    console.log('outbox closed');
    this.outbox = new WebSocket(outbox.url);
};

setInterval(
 function(event) {
  //event.preventDefault();
  var text  = $("#input-text")[0].value;
  var diff = dmp.diff_main(textShadow, text, true);
  if (diff.length > 2) {
    dmp.diff_cleanupSemantic(diff);
  }
  var patch_list = dmp.patch_make(textShadow, text, diff);
  var patch_text = dmp.patch_toText(patch_list);

  // send patch if exists
  if (patch_text) {
    // update shadow
    textShadow = text;
    outbox.send(JSON.stringify({ id: id, patch_text: patch_text }));
  }
}, 500);

