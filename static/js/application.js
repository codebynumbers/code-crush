// Editor config
var editor = ace.edit("input-text");
editor.setTheme("ace/theme/monokai");
editor.getSession().setMode("ace/mode/python");

var outbox = new ReconnectingWebSocket("ws://"+ location.host + "/submit/"+room);
var inbox = new ReconnectingWebSocket("ws://"+ location.host + "/receive/"+room);

var textShadow = "";
var dmp = new diff_match_patch();
var id = Math.floor(Math.random()*11);
var language = 'Python';

function setLanguage(lang, update_editor) {
  language = lang;
  $('#selected-language').html(language);

  // drop in boilerplate if need be
  if (editor.getValue() == "" && update_editor) {
    if (language == 'Java') {
      editor.setValue("class Main {\n    public static void main(String[] args) {\n\n    }\n}");
    } else if (language == 'PHP') {
      editor.setValue("<?php\n\n?>");
    }
  }
}

inbox.onmessage = function(message) {
  var data = JSON.parse(message.data);
  // ignore own patch, else patch text and shadow
  var from_self = (data.id == id)
  var text  = editor.getValue();

  if ( data.patch_text && !from_self) {
    var patches = dmp.patch_fromText(data.patch_text);
    var results = dmp.patch_apply(patches, text);
    shadowResults = dmp.patch_apply(patches, textShadow);
    textShadow = shadowResults[0];
    editor.setValue(results[0]);
  } else if (data.sync_needed && !from_self) {
    outbox.send(JSON.stringify({ id: id, full_text: text, language: language}));
  } else if (data.full_text && !from_self) {
    //console.log('updating full text');
    editor.setValue(data.full_text);
    textShadow = data.full_text;
    setLanguage(data.language);
  } else if (data.results !== undefined) {
    $("#results").html(data.results.replace(/\n/g, '<br>'));
  } else if (data.type == "lang") {
    setLanguage(data.language, !from_self);
  }
};

inbox.onclose = function(){
  //console.log('inbox closed');
  this.inbox = new WebSocket(inbox.url);
};

inbox.onopen = function(){
  // need to resync
  //console.log('asking for sync');
  outbox.send(JSON.stringify({ id: id, sync_needed: true}));
};

outbox.onclose = function(){
    //console.log('outbox closed');
    this.outbox = new WebSocket(outbox.url);
};

setInterval(
 function(event) {
  //event.preventDefault();
  var text = editor.getValue();
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


$(function(){

  $('#language-select a').click(function() {
    setLanguage($(this).html());
    outbox.send(JSON.stringify({ id: id, type: 'lang', language: language}));
  });

  $('#run').click(function(){
    var text  = editor.getValue();
    $("#results").html('evaluating ...');
    outbox.send(JSON.stringify({ id: id, full_text: text, type: 'run', language: language}));
  });

});
