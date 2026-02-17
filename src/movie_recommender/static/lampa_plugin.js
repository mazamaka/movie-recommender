/**
 * Movie Recommender -- Lampa Sync + Recommendations Plugin
 *
 * Установка: Lampa -> Настройки -> Дополнения -> добавить URL:
 * http://94.156.232.242:9200/static/lampa_plugin.js
 */
(function () {
    'use strict';

    var API_BASE = 'http://94.156.232.242:9200/api/v1';
    var SYNC_URL = API_BASE + '/sync';
    var REC_URL  = API_BASE + '/pipeline/recommendations';
    var SYNC_UID = 'default';

    // ==========================================
    // 1. Синхронизация истории просмотров
    // ==========================================

    function sendToServer(type, data) {
        try {
            var xhr = new XMLHttpRequest();
            xhr.open('POST', SYNC_URL + '/push', true);
            xhr.setRequestHeader('Content-Type', 'application/json');
            xhr.send(JSON.stringify({ uid: SYNC_UID, type: type, data: data }));
        } catch (e) {
            console.error('[MovieRec] Sync error:', e);
        }
    }

    Lampa.Listener.follow('full', function (e) {
        if (e.type === 'complite' && e.data && e.data.movie) {
            var movie = e.data.movie;
            sendToServer('history', [{
                title: movie.title || movie.name || '',
                year: movie.year || null,
                type: movie.media_type || 'movie',
                kp_id: movie.kp_id || null,
                imdb_id: movie.imdb_id || null,
                tmdb_id: movie.id || null,
                time: new Date().toISOString()
            }]);
        }
    });

    Lampa.Listener.follow('favorite', function (e) {
        if (e.type === 'add' || e.type === 'remove') {
            sendToServer('full', Lampa.Storage.get('favorite', '{}'));
        }
    });

    setTimeout(function () {
        sendToServer('full', Lampa.Storage.get('favorite', '{}'));
        console.log('[MovieRec] Initial sync sent');
    }, 5000);

    // ==========================================
    // 2. Рекомендации из нашего чата
    // ==========================================

    function startRecommendations() {
        if (window.movie_rec_ready) return;
        window.movie_rec_ready = true;

        function RecMainComponent(object) {
            var comp = new Lampa.InteractionMain(object);

            comp.create = function () {
                var _this = this;
                this.activity.loader(true);

                var network = new Lampa.Reguest();
                network.timeout(10000);

                network.silent(REC_URL, function (data) {
                    var results = data.results || [];
                    if (!results.length) {
                        _this.empty();
                        return;
                    }

                    // Deep clone each movie to avoid Lampa mutating shared refs
                    function cloneResults(arr) {
                        var out = [];
                        for (var i = 0; i < arr.length; i++) {
                            var o = {};
                            for (var k in arr[i]) o[k] = arr[i][k];
                            out.push(o);
                        }
                        return out;
                    }

                    var lines = [];

                    // Line 1: Все рекомендации
                    lines.push({
                        title: 'Все рекомендации',
                        results: cloneResults(results),
                        nomore: true
                    });

                    // Group by genres
                    var genreMap = {};
                    for (var i = 0; i < results.length; i++) {
                        var movie = results[i];
                        var genres = movie.genres || [];
                        for (var j = 0; j < genres.length; j++) {
                            var g = genres[j];
                            if (!genreMap[g]) genreMap[g] = [];
                            genreMap[g].push(movie);
                        }
                    }

                    // Sort genres by movie count descending
                    var genreKeys = Object.keys(genreMap);
                    genreKeys.sort(function (a, b) {
                        return genreMap[b].length - genreMap[a].length;
                    });

                    // Add genre lines (genres with at least 1 movie)
                    for (var k = 0; k < genreKeys.length; k++) {
                        var genre = genreKeys[k];
                        var movies = genreMap[genre];
                        if (movies.length >= 1) {
                            lines.push({
                                title: genre,
                                results: cloneResults(movies),
                                nomore: true
                            });
                        }
                    }

                    _this.build(lines);
                }, function () {
                    _this.empty();
                });

                return this.render();
            };

            return comp;
        }

        Lampa.Component.add('movie_rec_main', RecMainComponent);

        var icon = '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" fill="currentColor"/></svg>';

        var button = $('<li class="menu__item selector" data-action="movie_rec">' +
            '<div class="menu__ico">' + icon + '</div>' +
            '<div class="menu__text">Рекомендации</div>' +
            '</li>');

        button.on('hover:enter', function () {
            Lampa.Activity.push({
                url: '',
                title: 'Рекомендации',
                component: 'movie_rec_main',
                page: 1
            });
        });

        var menu = $('.menu .menu__list').eq(0);
        if (menu.length) {
            menu.prepend(button);
        }

        console.log('[MovieRec] Recommendations menu added');
    }

    if (window.appready) {
        startRecommendations();
    } else {
        Lampa.Listener.follow('app', function (e) {
            if (e.type === 'ready') startRecommendations();
        });
    }

    console.log('[MovieRec] Plugin loaded, server: ' + API_BASE);
})();
