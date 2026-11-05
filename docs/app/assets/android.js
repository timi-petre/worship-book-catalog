// Pe Android, Google cere conectarea doar în browserele care nu știu de
// contul telefonului: Samsung Internet, browserul din Instagram sau Facebook,
// alte webview-uri. Chrome îl știe și oferă „Continuă ca ...” dintr-o atingere.
// De aceea, în afara lui Chrome, linkurile Google se deschid prin Chrome
// (intent://), cu linkul obișnuit ca rezervă dacă Chrome lipsește.
// Pasul 3 merge direct în aplicația Magazin Play (market://).
(function () {
  var ua = navigator.userAgent;
  if (!/Android/.test(ua)) return;
  var chrome = /Chrome\//.test(ua) &&
    !/; wv\)|SamsungBrowser|EdgA|OPR|Firefox|YaBrowser|MiuiBrowser|HuaweiBrowser|Instagram|FBAN|FBAV/.test(ua);
  document.querySelectorAll('a[data-android]').forEach(function (a) {
    var url = a.href;
    if (a.dataset.android === 'magazin') {
      a.href = 'market://details?id=com.worship.worship_book';
    } else if (!chrome) {
      a.href = 'intent://' + url.replace(/^https:\/\//, '') +
        '#Intent;scheme=https;package=com.android.chrome;S.browser_fallback_url=' +
        encodeURIComponent(url) + ';end';
    }
  });
})();
