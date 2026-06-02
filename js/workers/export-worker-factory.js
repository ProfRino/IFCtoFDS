(function (ns) {
    ns.workers = ns.workers || {};
    var workerScriptUrl = new URL('fds-export-worker.js', document.currentScript.src).href;

    function createExportWorker() {
        if (window.location.protocol !== 'file:') {
            return {
                worker: new Worker(workerScriptUrl),
                url: null
            };
        }
        if (!window.IfcFdsExportWorkerSource) {
            throw new Error('The local background conversion bundle is missing. Open index.html from the complete IFCtoFDS folder.');
        }

        var url = URL.createObjectURL(
            new Blob([window.IfcFdsExportWorkerSource], { type: 'text/javascript' })
        );
        try {
            return {
                worker: new Worker(url),
                url: url
            };
        } catch (error) {
            URL.revokeObjectURL(url);
            throw error;
        }
    }

    ns.workers.createExportWorker = createExportWorker;
})(window.IfcFds);
