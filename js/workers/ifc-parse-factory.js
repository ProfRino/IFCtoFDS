(function (ns) {
    ns.workers = ns.workers || {};
    var workerScriptUrl = new URL('ifc-parse-shard-worker.js', document.currentScript.src).href;

    function createParseShardWorker() {
        if (window.location.protocol !== 'file:') {
            return { worker: new Worker(workerScriptUrl), url: null };
        }
        if (!window.IfcFdsParseShardWorkerSource) {
            throw new Error('The local parse-shard bundle is missing. Open index.html from the complete IFCtoFDS folder.');
        }
        var url = URL.createObjectURL(
            new Blob([window.IfcFdsParseShardWorkerSource], { type: 'text/javascript' })
        );
        try {
            return { worker: new Worker(url), url: url };
        } catch (error) {
            URL.revokeObjectURL(url);
            throw error;
        }
    }

    ns.workers.createParseShardWorker = createParseShardWorker;
})(window.IfcFds);
