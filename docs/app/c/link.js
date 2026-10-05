/* Pagina de rezervă a linkului de partajare, vezi c/index.html și, în
   aplicație, lib/services/share_payload.dart (singurul loc care scrie și
   citește payload-ul).

   Scriptul NU decodează payload-ul și nu scrie nimic din el pe pagină: doar
   îl mută, neschimbat, din fragmentul adresei https în adresa veche,
   cantaridelauda://program?d=..., pe care o înțelege și o aplicație mai
   veche de 1.6.0 (cea fără linkuri https). Validarea adevărată o face
   aplicația, cu plafonul ei de lungime; aici doar forma base64url decide
   care mesaj se vede. Textele stau toate în index.html. */
(function () {
  var d = new URLSearchParams(location.hash.slice(1)).get('d') || '';
  var ok = /^[A-Za-z0-9_-]+=*$/.test(d);
  document.getElementById(ok ? 'cu-link' : 'fara-link').hidden = false;
  if (ok) {
    document.getElementById('deschide').href =
      'cantaridelauda://program?d=' + encodeURIComponent(d);
  }
})();
