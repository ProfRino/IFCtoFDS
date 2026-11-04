"""Real upload/worker/chunk import, with whole-file JS reads prohibited."""

import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.browser
def test_large_upload_avoids_browser_step_decoding(tiny_ifc, tmp_path):
    from playwright.sync_api import sync_playwright

    source, file, wall = tiny_ifc
    import numpy as np
    import ifcopenshell.api.geometry

    placement = np.eye(4)
    placement[:3, 3] = [600000.123456, 2400000.987654, 0]
    ifcopenshell.api.geometry.edit_object_placement(
        file, product=wall, matrix=placement
    )
    # Cross a batch boundary with real IFC products and shared native geometry.
    for i in range(16):
        file.create_entity(
            "IfcWall",
            GlobalId=ifcopenshell.guid.new(),
            Name=f"Batch wall {i}",
            ObjectPlacement=wall.ObjectPlacement,
            Representation=wall.Representation,
        )
    file.write(str(source))
    large = tmp_path / "large.ifc"
    with large.open("wb") as output:
        output.write(source.read_bytes())
        for _ in range(33):
            output.write(b" " * 1024**2)
    if os.environ.get("IFCFDS_PREVIEW_TEST_SOURCE"):
        large = Path(os.environ["IFCFDS_PREVIEW_TEST_SOURCE"])
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    with (tmp_path / "server.log").open("w", encoding="utf-8") as log:
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "ifc_to_fds.server:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=ROOT,
            stdout=log,
            stderr=log,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            for _ in range(100):
                try:
                    urllib.request.urlopen(url + "/api/health", timeout=1).close()
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Preview test server did not start")
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--enable-webgl", "--use-angle=swiftshader"],
                    **({"channel": "msedge"} if os.name == "nt" else {}),
                )
                try:
                    page = browser.new_page()
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(url, wait_until="networkidle")
                    page.evaluate("""() => {
                        const realFetch = window.fetch;
                        window.fetch = async function(url, options) {
                            const result = await realFetch(url, options);
                            if (String(url).endsWith('/result') && result.ok) window.previewResult = await result.clone().json();
                            return result;
                        };
                        File.prototype.arrayBuffer = function() { throw new Error('Whole source buffer forbidden'); };
                        File.prototype.text = function() { throw new Error('Whole source text forbidden'); };
                        IfcFds.ifc.IfcAdapter.prototype.parseAsync = function() { throw new Error('Legacy parse forbidden'); };
                    }""")
                    page.set_input_files("#ifc-file", large)
                    page.wait_for_function(
                        "IfcFds.workbench.state.selectionStore.getAllDescriptors().length > 0",
                        timeout=1800000,
                    )
                    assert page.evaluate(
                        "IfcFds.workbench.navigation.colorOverlay.viewer.ifcSolidGroup.children.length === previewResult.rendered_elements"
                    )
                    if not os.environ.get("IFCFDS_PREVIEW_TEST_SOURCE"):
                        assert page.evaluate("previewResult.rendered_elements") == 17
                    assert page.locator(
                        "#verified-storeys option"
                    ).count() == page.evaluate("previewResult.storeys.length")
                    page.wait_for_function(
                        "!document.getElementById('convert-verified').disabled",
                        timeout=10000,
                    )
                    assert page.locator("#convert-ifc").is_disabled()
                    # Real controller handlers must never promote preview metadata
                    # to a Quick Conversion model after state changes.
                    for option in ("include-fill-solids", "include-review-solids"):
                        for checked in (True, False):
                            page.locator("#" + option).evaluate(
                                "(node, checked) => { node.checked = checked; node.dispatchEvent(new Event('change', {bubbles:true})); }",
                                checked,
                            )
                            assert page.locator("#convert-ifc").is_disabled()
                    page.evaluate("""() => {
                        const viewer = IfcFds.workbench.navigation.colorOverlay.viewer;
                        const pickCandidate = viewer.pickCandidate;
                        try {
                            viewer.pickCandidate = () => ({object: viewer.ifcSolidGroup.children[0]});
                            viewer.handleClick({clientX: 0, clientY: 0});
                        } finally {
                            viewer.pickCandidate = pickCandidate;
                        }
                    }""")
                    assert page.locator("#delete-selected-ifc").is_enabled()
                    page.locator("#delete-selected-ifc").evaluate("node => node.click()")
                    assert page.locator("#undo-last").is_enabled()
                    assert page.locator("#convert-ifc").is_disabled()
                    page.locator("#undo-last").evaluate("node => node.click()")
                    assert page.locator("#convert-ifc").is_disabled()
                    identity = page.evaluate("""() => {
                        const v = IfcFds.workbench.navigation.colorOverlay.viewer;
                        const mesh = v.ifcSolidGroup.children[0];
                        const key = mesh.userData.entityKey;
                        return {key, indexed:IfcFds.workbench.state.selectionStore.getAllDescriptors().some(d => d.entityKey === key),
                            vertices:mesh.geometry.attributes.position.count};
                    }""")
                    assert len(identity["key"].split(":")[0]) == 64
                    assert identity["indexed"] and identity["vertices"] > 0
                    assert page.evaluate("""() => {
                        const v = IfcFds.workbench.navigation.colorOverlay.viewer;
                        const box = new THREE.Box3().setFromObject(v.ifcSolidGroup), b = previewResult.bounds;
                        let edges = 0;
                        v.ifcSolidGroup.traverse(n => { if (n._isIfcEdge) edges++; });
                        return edges === 0 && Math.abs(box.min.x-b.xmin) < 1e-4 && Math.abs(box.max.x-b.xmax) < 1e-4 &&
                            Math.abs(box.min.z-b.ymin) < 1e-4 && Math.abs(box.max.z-b.ymax) < 1e-4;
                    }""")
                    assert page.evaluate("""() => {
                        const v = IfcFds.workbench.navigation.colorOverlay.viewer;
                        const x=600000.123456, y=2400000.987654;
                        const vertices=[[x,y,0],[x+2,y,0],[x+2,y+.03,0],[x,y+.03,0],
                                        [x,y,3],[x+2,y,3],[x+2,y+.03,3],[x,y+.03,3]];
                        const faces=[[0,2,1],[0,3,2],[4,5,6],[4,6,7],[0,1,5],[0,5,4],
                                     [1,2,6],[1,6,5],[2,3,7],[2,7,6],[3,0,4],[3,4,7]];
                        const geom=v.makeGeom({type:'mesh', id:'far-thin', vertices, faces});
                        const box=v.makeBox({id:'far-box', xb:[x,x+2,y,y+.03,0,3]},0x999999,'OBST',false);
                        const g=new THREE.Box3().setFromObject(geom), b=new THREE.Box3().setFromObject(box);
                        return Math.abs(g.max.z-g.min.z-.03)<1e-6 && Math.abs(b.max.z-b.min.z-.03)<1e-6;
                    }""")
                    page.screenshot(path=str(tmp_path / "preview.png"))
                    import json

                    (tmp_path / "preview-result.json").write_text(
                        json.dumps(page.evaluate("previewResult"), indent=2),
                        encoding="utf-8",
                    )
                    assert not errors
                finally:
                    browser.close()
        finally:
            server.terminate()
            server.wait(timeout=15)
