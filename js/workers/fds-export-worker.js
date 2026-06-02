self.window = self;

importScripts(
    '../core/namespace.js',
    '../core/diagnostics.js',
    '../fds/fds-exporter.js',
    '../fds/namelist-parser.js',
    '../fds/fds-geometry-adapter.js'
);

var exporter = new self.IfcFds.fds.FdsExporter();
var parser = new self.IfcFds.fds.FdsNamelistParser();
var adapter = new self.IfcFds.fds.FdsGeometryAdapter();

self.onmessage = function (event) {
    var request = event.data || {};
    if (request.type !== 'export') return;

    try {
        var options = request.options || {};
        options.onProgress = function (fraction, stage) {
            self.postMessage({
                type: 'progress',
                requestId: request.requestId,
                fraction: fraction,
                stage: stage || ''
            });
        };
        var text = exporter.exportFromIfcScene(request.ifcModel, options);
        var model = adapter.toSceneModel(parser.parse(text));
        self.postMessage({
            type: 'complete',
            requestId: request.requestId,
            text: text,
            model: model
        });
    } catch (error) {
        self.postMessage({
            type: 'error',
            requestId: request.requestId,
            message: error && error.message ? error.message : String(error)
        });
    }
};
