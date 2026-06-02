(function (ns) {
    function Diagnostic(level, title, detail, ref) {
        this.level = level || 'info';
        this.title = title || 'Notice';
        this.detail = detail || '';
        this.ref = ref || null;
    }

    function add(list, level, title, detail, ref) {
        list.push(new Diagnostic(level, title, detail, ref));
        return list;
    }

    ns.core.Diagnostic = Diagnostic;
    ns.core.addDiagnostic = add;
})(window.IfcFds);
