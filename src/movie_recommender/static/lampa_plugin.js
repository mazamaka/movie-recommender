/**
 * Movie Recommender -- Lampa Sync Plugin
 * Автоматически отправляет историю просмотров на sync сервер.
 *
 * Установка: в Lampa -> Настройки -> Дополнения -> добавить URL плагина:
 * http://94.156.232.242:9200/static/lampa_plugin.js
 */
(function () {
    'use strict';

    var SYNC_URL = window.lampa_settings && window.lampa_settings.sync_url
        || 'http://94.156.232.242:9200/api/v1/sync';
    var SYNC_UID = window.lampa_settings && window.lampa_settings.sync_uid || 'default';

    function sendToServer(type, data) {
        try {
            var xhr = new XMLHttpRequest();
            xhr.open('POST', SYNC_URL + '/push', true);
            xhr.setRequestHeader('Content-Type', 'application/json');
            xhr.send(JSON.stringify({
                uid: SYNC_UID,
                type: type,
                data: data
            }));
        } catch (e) {
            console.error('[MovieRec] Sync error:', e);
        }
    }

    // Синхронизация при просмотре фильма
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

    // Синхронизация закладок при изменении
    Lampa.Listener.follow('favorite', function (e) {
        if (e.type === 'add' || e.type === 'remove') {
            var fav = Lampa.Storage.get('favorite', '{}');
            sendToServer('full', fav);
        }
    });

    // Полная синхронизация при запуске (с задержкой)
    setTimeout(function () {
        var fav = Lampa.Storage.get('favorite', '{}');
        sendToServer('full', fav);
        console.log('[MovieRec] Initial sync sent');
    }, 5000);

    console.log('[MovieRec] Sync plugin loaded, server: ' + SYNC_URL);
})();
