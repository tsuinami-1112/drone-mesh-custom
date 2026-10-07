// Fills the release line in the header and footer from version.json, which
// flasher/build_site.py writes when the Firmware workflow publishes. A local
// copy of the page without that file just says "preview".
//
// This lives in its own file on purpose: the page's Content-Security-Policy
// only runs scripts served by the site itself, so an inline <script> block
// in index.html would be blocked.
(function () {
  var repo = 'https://github.com/tsuinami-1112/drone-sentinel';
  fetch('version.json', { cache: 'no-store' })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (v) {
      if (!v || !v.version) return;
      var tag = encodeURIComponent(v.version);
      var commit = (v.commit || '').slice(0, 7);
      var release = document.getElementById('release');
      release.textContent = 'RELEASE ';
      var a = document.createElement('a');
      a.href = repo + '/releases/tag/' + tag;
      a.textContent = v.version;
      release.appendChild(a);
      release.appendChild(document.createTextNode(' · ' + (v.date || '') + (commit ? ' · ' + commit : '')));
      document.getElementById('footer-release').textContent =
        'Release ' + v.version + (v.date ? ' · built ' + v.date : '') + (commit ? ' from ' + commit : '');
    })
    .catch(function () {});
})();
