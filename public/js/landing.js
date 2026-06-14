/* AetherOS landing page — Three.js hero + scroll reveal + card tilt */
(function () {
  'use strict';

  /* ── 1. THREE.JS ICOSAHEDRON HERO ── */
  var canvas = document.getElementById('hero-canvas');
  if (canvas && window.THREE) {
    var W = window.innerWidth, H = window.innerHeight;
    var scene = new THREE.Scene();
    var camera = new THREE.PerspectiveCamera(55, W / H, 0.1, 1000);
    camera.position.z = 5;

    var renderer = new THREE.WebGLRenderer({ canvas: canvas, alpha: true, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(W, H);
    renderer.setClearColor(0x000000, 0);

    /* Icosahedron wireframe */
    var geoIco = new THREE.IcosahedronGeometry(1.6, 1);
    var matIco = new THREE.MeshBasicMaterial({
      color: 0x7c3aed, wireframe: true,
      transparent: true, opacity: 0.22
    });
    var mesh = new THREE.Mesh(geoIco, matIco);
    scene.add(mesh);

    /* Second faint larger icosahedron */
    var geoIco2 = new THREE.IcosahedronGeometry(2.6, 1);
    var matIco2 = new THREE.MeshBasicMaterial({
      color: 0x4f46e5, wireframe: true,
      transparent: true, opacity: 0.07
    });
    var mesh2 = new THREE.Mesh(geoIco2, matIco2);
    scene.add(mesh2);

    /* Particle field */
    var N = 700;
    var positions = new Float32Array(N * 3);
    for (var i = 0; i < N; i++) {
      var r = 2.5 + Math.random() * 4;
      var theta = Math.random() * Math.PI * 2;
      var phi = Math.acos(2 * Math.random() - 1);
      positions[i * 3]     = r * Math.sin(phi) * Math.cos(theta);
      positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
      positions[i * 3 + 2] = r * Math.cos(phi);
    }
    var geoPts = new THREE.BufferGeometry();
    geoPts.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    var matPts = new THREE.PointsMaterial({
      color: 0x9f7aea, size: 0.022,
      transparent: true, opacity: 0.55
    });
    var points = new THREE.Points(geoPts, matPts);
    scene.add(points);

    /* Mouse parallax */
    var mouseX = 0, mouseY = 0;
    document.addEventListener('mousemove', function (e) {
      mouseX = (e.clientX / W - 0.5) * 2;
      mouseY = (e.clientY / H - 0.5) * 2;
    });

    /* Scroll fade-out */
    var scrollPct = 0;
    window.addEventListener('scroll', function () {
      scrollPct = Math.min(window.scrollY / (H * 0.6), 1);
      canvas.style.opacity = (0.85 * (1 - scrollPct * 1.4)).toString();
    });

    /* Resize */
    window.addEventListener('resize', function () {
      W = window.innerWidth; H = window.innerHeight;
      camera.aspect = W / H;
      camera.updateProjectionMatrix();
      renderer.setSize(W, H);
    });

    /* Animate */
    var clock = new THREE.Clock();
    function animate() {
      requestAnimationFrame(animate);
      var t = clock.getElapsedTime();
      mesh.rotation.x  = t * 0.12 + mouseY * 0.15;
      mesh.rotation.y  = t * 0.18 + mouseX * 0.15;
      mesh2.rotation.x = -t * 0.07 + mouseY * 0.06;
      mesh2.rotation.y = t * 0.11 + mouseX * 0.06;
      points.rotation.y = t * 0.04;
      renderer.render(scene, camera);
    }
    animate();
  }

  /* ── 2. SCROLL REVEAL ── */
  var reveals = document.querySelectorAll('[data-reveal]');
  if (reveals.length) {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          e.target.classList.add('revealed');
          observer.unobserve(e.target);
        }
      });
    }, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });

    reveals.forEach(function (el) { observer.observe(el); });

    /* Immediately reveal anything already in viewport */
    setTimeout(function () {
      reveals.forEach(function (el) {
        var rect = el.getBoundingClientRect();
        if (rect.top < window.innerHeight) el.classList.add('revealed');
      });
    }, 80);
  }

  /* ── 3. CARD TILT ── */
  document.querySelectorAll('.tilt').forEach(function (card) {
    card.addEventListener('mousemove', function (e) {
      var r = card.getBoundingClientRect();
      var cx = (e.clientX - r.left) / r.width  - 0.5;
      var cy = (e.clientY - r.top)  / r.height - 0.5;
      card.style.transform = 'perspective(800px) rotateY(' + (cx * 8) + 'deg) rotateX(' + (-cy * 6) + 'deg) scale(1.02)';
    });
    card.addEventListener('mouseleave', function () {
      card.style.transform = '';
    });
  });

  /* ── 4. NAV SCROLL STATE ── */
  window.addEventListener('scroll', function () {
    var nav = document.querySelector('nav');
    if (nav) {
      nav.style.background = window.scrollY > 40
        ? 'rgba(5,5,7,0.95)'
        : 'rgba(5,5,7,0.75)';
    }
  });

})();
