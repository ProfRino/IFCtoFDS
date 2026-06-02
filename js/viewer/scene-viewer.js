(function (ns) {
    function SceneViewer(container, onSelect) {
        this.container = container;
        this.onSelect = onSelect || function () {};
        this.scene = new THREE.Scene();
        this.scene.background = new THREE.Color(0xf4f5f8);
        this.camera = new THREE.PerspectiveCamera(55, 1, 0.1, 5000);
        this.renderer = new THREE.WebGLRenderer({ antialias: true });
        this.renderer.localClippingEnabled = true;
        // Six clipping planes track the user's clip-bar sliders. Plane normals point INTO the
        // kept region. Inactive (no clip) = constant pushed far away so nothing gets cut.
        this.clipPlanes = [
            new THREE.Plane(new THREE.Vector3(1, 0, 0), Infinity),   // X min (keep X >= xmin)
            new THREE.Plane(new THREE.Vector3(-1, 0, 0), Infinity),  // X max (keep X <= xmax)
            new THREE.Plane(new THREE.Vector3(0, 1, 0), Infinity),   // Y min
            new THREE.Plane(new THREE.Vector3(0, -1, 0), Infinity),  // Y max
            new THREE.Plane(new THREE.Vector3(0, 0, 1), Infinity),   // Z min
            new THREE.Plane(new THREE.Vector3(0, 0, -1), Infinity)   // Z max
        ];
        this.clipBoundsNative = null;
        this.renderer.clippingPlanes = this.clipPlanes;
        this.controls = null;
        this.walkControls = null;
        this.onNavigationModeChange = function () {};
        this.navigationMode = 'orbit';
        this.walkFloorY = 0;
        this.walkEyeHeight = 1.65;
        this.walkPlaced = false;
        this.walkVelocityY = 0;
        this.walkSpeed = 1.8;
        this.walkRunMultiplier = 2.5;
        this.walkRadius = 0.3;
        this.walkGravity = 9.81;
        this.walkStepHeight = 0.45;
        this.walkRaycaster = new THREE.Raycaster();
        this.walkSavedCamera = null;
        this.walkMovement = {
            forward: false,
            backward: false,
            left: false,
            right: false,
            jump: false,
            fast: false
        };
        this.lastFrameTime = 0;
        this.fdsGroup = new THREE.Group();
        this.ifcGroup = new THREE.Group();
        this.meshGroup = new THREE.Group();
        this.obstGroup = new THREE.Group();
        this.ventGroup = new THREE.Group();
        this.holeGroup = new THREE.Group();
        this.geomGroup = new THREE.Group();
        this.ifcSolidGroup = new THREE.Group();
        this.ifcReferenceGroup = new THREE.Group();
        this.groundGrid = null;
        this.raycaster = new THREE.Raycaster();
        this.raycaster.params.Line.threshold = 0.05;
        this.mouse = new THREE.Vector2();
        this.theme = 'light';
        this.viewMode = 'overlay';
        this.showIfcEdges = true;
        this.opacity = 0.72;
        this.ifcOpacity = 1;
        this.hoveredObject = null;
        this.selectedObjects = [];
        this.selectionHelpers = [];
        this.tooltip = null;

        this.init();
    }

    SceneViewer.prototype.init = function () {
        this.renderer.setPixelRatio(window.devicePixelRatio || 1);
        this.renderer.setSize(this.container.clientWidth, this.container.clientHeight);
        this.renderer.outputEncoding = THREE.sRGBEncoding;
        this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
        this.renderer.toneMappingExposure = 1.0;
        this.container.appendChild(this.renderer.domElement);

        this.controls = new THREE.OrbitControls(this.camera, this.renderer.domElement);
        this.controls.enableDamping = true;
        this.controls.dampingFactor = 0.08;
        this.walkControls = new THREE.PointerLockControls(this.camera, this.renderer.domElement);

        this.camera.position.set(10, 8, 10);
        this.controls.target.set(0, 0, 0);

        var hemi = new THREE.HemisphereLight(0xffffff, 0xb8bcc4, 0.9);
        var key = new THREE.DirectionalLight(0xffffff, 0.8);
        key.position.set(6, 14, 8);
        var fill = new THREE.DirectionalLight(0xffffff, 0.2);
        fill.position.set(-6, 4, -8);
        this.scene.add(hemi, key, fill);

        this.groundGrid = new THREE.GridHelper(2000, 2000, 0xa9afbd, 0xd8dae2);
        this.groundGrid.name = 'Ground grid';
        this.groundGrid.material.transparent = true;
        this.groundGrid.material.opacity = 0.42;
        this.groundGrid.material.depthWrite = false;
        // Opt the ground grid out of the global clipping planes — the grid is a UI helper
        // that should always extend to the camera horizon regardless of the clip-bar state.
        this.groundGrid.material.clippingPlanes = [];
        this.scene.add(this.groundGrid);

        this.fdsGroup.name = 'FDS';
        this.ifcGroup.name = 'IFC';
        this.ifcSolidGroup.name = 'IFC solids';
        this.ifcReferenceGroup.name = 'IFC reference';
        this.scene.add(this.fdsGroup, this.ifcGroup);
        this.fdsGroup.add(this.meshGroup, this.obstGroup, this.ventGroup, this.holeGroup, this.geomGroup);
        this.ifcGroup.add(this.ifcSolidGroup, this.ifcReferenceGroup);
        this.ifcReferenceGroup.visible = false;

        this.tooltip = document.createElement('div');
        this.tooltip.className = 'hover-tooltip';
        this.tooltip.hidden = true;
        this.container.appendChild(this.tooltip);

        window.addEventListener('resize', this.resize.bind(this));
        window.addEventListener('keydown', this.handleWalkKey.bind(this, true));
        window.addEventListener('keyup', this.handleWalkKey.bind(this, false));
        this.renderer.domElement.addEventListener('click', this.handleClick.bind(this));
        this.renderer.domElement.addEventListener('pointermove', this.handlePointerMove.bind(this));
        this.renderer.domElement.addEventListener('pointerleave', this.clearHover.bind(this));
        this.renderer.domElement.addEventListener('pointerdown', this.handlePointerDown.bind(this));
        this.renderer.domElement.addEventListener('pointerup', this.handlePointerUp.bind(this));
        this.marqueeEl = this.container.querySelector('#marquee') || document.getElementById('marquee');
        this.marqueeState = null;
        this.walkControls.addEventListener('unlock', this.handleWalkUnlock.bind(this));
        this.resize();
        this.animate();
    };

    SceneViewer.prototype.animate = function (time) {
        requestAnimationFrame(this.animate.bind(this));
        var delta = this.lastFrameTime ? Math.min((time - this.lastFrameTime) / 1000, 0.1) : 0;
        this.lastFrameTime = time;
        if (this.navigationMode === 'walk') this.updateWalkMovement(delta);
        else this.controls.update();
        this.updateGroundGrid();
        this.renderer.render(this.scene, this.camera);
    };

    SceneViewer.prototype.updateGroundGrid = function () {
        if (!this.groundGrid || !this.controls) return;
        var target = this.navigationMode === 'walk' ? this.camera.position : this.controls.target;
        this.groundGrid.position.x = Math.round(target.x);
        this.groundGrid.position.z = Math.round(target.z);
    };

    SceneViewer.prototype.resize = function () {
        var width = Math.max(1, this.container.clientWidth);
        var height = Math.max(1, this.container.clientHeight);
        this.camera.aspect = width / height;
        this.camera.updateProjectionMatrix();
        this.renderer.setSize(width, height);
    };

    SceneViewer.prototype.loadFdsModel = function (model) {
        this.setNavigationMode('orbit');
        this.setSelectedObjects([]);
        clearGroup(this.meshGroup);
        clearGroup(this.obstGroup);
        clearGroup(this.ventGroup);
        clearGroup(this.holeGroup);
        clearGroup(this.geomGroup);

        var self = this;
        (model.meshes || []).forEach(function (mesh) { self.meshGroup.add(self.makeWireBox(mesh, 0x4488ff, 'MESH')); });
        (model.obsts || []).forEach(function (obst) { self.obstGroup.add(self.makeBox(obst, 0xb0b0c0, 'OBST')); });
        (model.vents || []).forEach(function (vent) { self.ventGroup.add(self.makeBox(vent, 0xff6b35, 'VENT', true)); });
        (model.holes || []).forEach(function (hole) { self.holeGroup.add(self.makeBox(hole, 0x00e5ff, 'HOLE', true)); });
        (model.geoms || []).forEach(function (geom) { self.geomGroup.add(self.makeGeom(geom)); });

        // Opt FDS materials out of the global smooth clipping — for FDS the clip bars are
        // expected to make whole primitives appear/disappear rather than slicing through them.
        // applyFdsClipVisibility() below toggles each mesh.visible based on its world bbox.
        this.fdsGroup.traverse(function (node) {
            if (node.material && node.material.isMaterial) {
                node.material.clippingPlanes = [];
            }
        });

        this.clearHover();
        this.applyFdsClipVisibility();
    };

    SceneViewer.prototype.loadIfcModel = function (model, displayMeshes) {
        this.setNavigationMode('orbit');
        this.setSelectedObjects([]);
        clearGroup(this.ifcSolidGroup);
        clearGroup(this.ifcReferenceGroup);

        if (displayMeshes && displayMeshes.length) {
            this.addWebIfcDisplayMeshes(model, displayMeshes);
        } else {
            var self = this;
            (model.elements || []).forEach(function (element) {
                var group = element.reference === true ? self.ifcReferenceGroup : self.ifcSolidGroup;
                group.add(self.makeIfcElement(element));
            });
        }

        this.clearHover();
        this.applyIfcCategoryVisibility();
        if (model.convertibleBounds || model.bounds) {
            this.fitToBounds(model.convertibleBounds || model.bounds);
        } else {
            this.fitToWorldBox();
        }
    };

    // Canonical view shortcuts (1=front, 2=back, 3=left, 4=right, 5=top, 6=bottom, 0=iso),
    // matching ProfRino/fds-viewer's keymap. Frame is computed from the visible IFC + FDS
    // groups so the building stays in shot regardless of which model is loaded.
    SceneViewer.prototype.setView = function (direction) {
        this.ifcGroup.updateMatrixWorld(true);
        this.fdsGroup.updateMatrixWorld(true);
        var box = new THREE.Box3();
        if (this.ifcGroup.visible) box.expandByObject(this.ifcGroup);
        if (this.fdsGroup.visible) box.expandByObject(this.fdsGroup);
        if (box.isEmpty()) {
            box.expandByObject(this.ifcGroup);
            box.expandByObject(this.fdsGroup);
        }
        if (box.isEmpty()) return;
        var center = box.getCenter(new THREE.Vector3());
        var size = box.getSize(new THREE.Vector3());
        var dist = Math.max(size.x, size.y, size.z, 1) * 1.6;

        this.setNavigationMode('orbit');
        this.controls.target.copy(center);
        switch (direction) {
            case 'front':
                this.camera.position.set(center.x, center.y, center.z + dist);
                break;
            case 'back':
                this.camera.position.set(center.x, center.y, center.z - dist);
                break;
            case 'left':
                this.camera.position.set(center.x - dist, center.y, center.z);
                break;
            case 'right':
                this.camera.position.set(center.x + dist, center.y, center.z);
                break;
            case 'top':
                this.camera.position.set(center.x, center.y + dist, center.z);
                break;
            case 'bottom':
                this.camera.position.set(center.x, center.y - dist, center.z);
                break;
            case 'iso':
            default:
                this.camera.position.set(
                    center.x + dist * 0.7,
                    center.y + dist * 0.55,
                    center.z + dist * 0.7
                );
                break;
        }
        this.camera.near = Math.max(dist / 500, 0.02);
        this.camera.far = dist * 50;
        this.camera.updateProjectionMatrix();
        this.controls.update();
    };

    // Arrow-key orbit/zoom for the desktop user, mirroring how ProfRino/fds-viewer drives
    // the camera with the keyboard:
    //   left  / right  → orbit yaw around the target (counter-/clockwise)
    //   up    / down   → orbit pitch (raise / lower the camera)
    //   shift + left/right → strafe target sideways instead of orbit
    //   shift + up/down    → dolly in / out (the same effect the mouse wheel has)
    // The walk-mode keyboard handler owns WASD + arrow keys separately and takes priority,
    // so this method early-outs when navigationMode is 'walk'.
    SceneViewer.prototype.orbitByKey = function (direction, modifiers) {
        if (this.navigationMode !== 'orbit' || !this.controls) return false;
        modifiers = modifiers || {};
        var camera = this.camera;
        var target = this.controls.target;
        var offset = new THREE.Vector3().subVectors(camera.position, target);
        var radius = offset.length();
        var spherical = new THREE.Spherical().setFromVector3(offset);
        var rotateStep = Math.PI / 36; // 5°
        var dollyStep = 1.12;
        var panStep = radius * 0.05;

        if (modifiers.shift && (direction === 'up' || direction === 'down')) {
            // Shift + vertical → dolly. Up zooms in, down zooms out.
            offset.multiplyScalar(direction === 'up' ? 1 / dollyStep : dollyStep);
        } else if (modifiers.shift && (direction === 'left' || direction === 'right')) {
            // Shift + horizontal → strafe the target & camera together along the camera's
            // right vector so the orbit pivot itself moves.
            var right = new THREE.Vector3();
            camera.getWorldDirection(right);
            right.cross(camera.up).normalize().multiplyScalar(direction === 'right' ? panStep : -panStep);
            target.add(right);
            camera.position.add(right);
            this.controls.update();
            return true;
        } else if (direction === 'left') {
            spherical.theta -= rotateStep;
            offset.setFromSpherical(spherical);
        } else if (direction === 'right') {
            spherical.theta += rotateStep;
            offset.setFromSpherical(spherical);
        } else if (direction === 'up') {
            spherical.phi = Math.max(0.05, spherical.phi - rotateStep);
            offset.setFromSpherical(spherical);
        } else if (direction === 'down') {
            spherical.phi = Math.min(Math.PI - 0.05, spherical.phi + rotateStep);
            offset.setFromSpherical(spherical);
        } else {
            return false;
        }

        camera.position.copy(target).add(offset);
        camera.lookAt(target);
        this.controls.update();
        return true;
    };

    // Clipping is driven by 6 sliders along the bottom of the viewer. The slider values are
    // in IFC-native coordinates (X east, Y north, Z up); we translate to Three.js world axes
    // here because toThree() does a Y/Z swap. clipBoundsNative caches the world span so the
    // sliders stay in lock-step with the model whenever a new IFC is loaded.
    SceneViewer.prototype.setClipBoundsNative = function (nativeBounds) {
        if (!nativeBounds) { this.clipBoundsNative = null; this.resetClipping(); return; }
        this.clipBoundsNative = {
            xmin: nativeBounds.xmin, xmax: nativeBounds.xmax,
            ymin: nativeBounds.ymin, ymax: nativeBounds.ymax,
            zmin: nativeBounds.zmin, zmax: nativeBounds.zmax
        };
        this.resetClipping();
    };

    // axis: 'x' | 'y' | 'z', side: 'min' | 'max'. Value is in IFC-native coords.
    SceneViewer.prototype.setClipPlane = function (axis, side, value) {
        if (!this.clipPlanes) return;
        // IFC X -> Three X, IFC Y -> Three Z, IFC Z -> Three Y (per toThree).
        if (axis === 'x') {
            if (side === 'min') this.clipPlanes[0].constant = -value;
            else this.clipPlanes[1].constant = value;
        } else if (axis === 'y') {
            if (side === 'min') this.clipPlanes[4].constant = -value;
            else this.clipPlanes[5].constant = value;
        } else if (axis === 'z') {
            if (side === 'min') this.clipPlanes[2].constant = -value;
            else this.clipPlanes[3].constant = value;
        }
        this.clipRanges = this.clipRanges || { xmin: -Infinity, xmax: Infinity, ymin: -Infinity, ymax: Infinity, zmin: -Infinity, zmax: Infinity };
        this.clipRanges[axis + side] = value;
        this.applyFdsClipVisibility();
    };

    // Per-primitive discrete clipping for the FDS group. An OBST/GEOM/VENT mesh is shown
    // only when its full world bbox sits inside the current clip box — so as the user drags
    // a clip slider, individual primitives appear/disappear whole rather than being sliced.
    // The smooth fragment-clip is still applied to the IFC materials.
    SceneViewer.prototype.applyFdsClipVisibility = function () {
        var range = this.clipRanges;
        var excludedSteps = this.excludedStepIds || {};
        var excludedItems = this.excludedItemIds || {};
        var noActiveClip = !range || (
            range.xmin === -Infinity && range.xmax === Infinity
            && range.ymin === -Infinity && range.ymax === Infinity
            && range.zmin === -Infinity && range.zmax === Infinity
        );
        this.fdsGroup.updateMatrixWorld(true);
        var box = new THREE.Box3();
        this.fdsGroup.traverse(function (node) {
            if (!node.isMesh && !node.isLineSegments) return;
            if (isExcludedMesh(node, excludedSteps, excludedItems)) { node.visible = false; return; }
            if (noActiveClip) { node.visible = true; return; }
            box.makeEmpty().expandByObject(node);
            if (box.isEmpty()) { node.visible = true; return; }
            // Three world -> IFC native: Three Y is IFC Z (height), Three Z is IFC Y.
            var inside = box.min.x >= range.xmin && box.max.x <= range.xmax
                && box.min.y >= range.zmin && box.max.y <= range.zmax
                && box.min.z >= range.ymin && box.max.z <= range.ymax;
            node.visible = inside;
        });
    };

    // Plays a two-phase "reveal" animation after a conversion: IFC snaps to full opacity
    // and eases away to zero, then the FDS group is uncovered bottom-up by a temporary
    // per-material clip plane. Falls back gracefully (and instantly) if the FDS group is
    // empty or clipping isn't supported. Cleans up its own state on finish so the user's
    // own clip-bar settings keep working.
    SceneViewer.prototype.playConversionReveal = function (options) {
        options = options || {};
        var fadeMs = Math.max(0, Number(options.fadeMs) || 1400);
        var finalIfcOpacity = typeof options.finalIfcOpacity === 'number' ? options.finalIfcOpacity : 0.15;
        var onComplete = typeof options.onComplete === 'function' ? options.onComplete : function () {};
        var self = this;

        // Clear any prior clip state so a stale partial clip box from before this convert
        // doesn't hide the freshly-produced FDS primitives during the reveal. The clip-bar
        // UI is re-synced by the controller right after this call.
        this.resetClipping();
        this.fdsGroup.updateMatrixWorld(true);
        var box = new THREE.Box3().expandByObject(this.fdsGroup);
        if (box.isEmpty()) { onComplete(); return; }

        // Scale the reveal duration with the building height so a tall building (Institute,
        // school) doesn't blow past in the same 2.2 s as a single-storey house. Caller can
        // still override via options.revealMs.
        var height = Math.max(0.01, box.max.y - box.min.y);
        var revealMs = Math.max(0, Number(options.revealMs) || Math.max(2200, Math.min(6000, height * 350)));

        // Stop any in-flight reveal so back-to-back conversions don't double-animate.
        if (this._revealCleanup) { this._revealCleanup(); this._revealCleanup = null; }

        var yMin = box.min.y - 0.01;
        var yMax = box.max.y + 0.01;
        var revealPlane = new THREE.Plane(new THREE.Vector3(0, -1, 0), yMin);
        var savedClips = [];
        this.fdsGroup.traverse(function (node) {
            if (node.material && node.material.isMaterial) {
                savedClips.push({ material: node.material, previous: node.material.clippingPlanes });
                node.material.clippingPlanes = [revealPlane];
            }
        });

        this.setIfcOpacity(1);

        var startTime = performance.now();
        var animFrame = null;
        var finished = false;
        function cleanup() {
            if (finished) return;
            finished = true;
            savedClips.forEach(function (entry) { entry.material.clippingPlanes = entry.previous; });
            // Land the IFC at the configured final opacity (default 0.3) so it stays as a
            // ghosted backdrop next to the FDS. Push the slider too so the UI reflects it.
            self.setIfcOpacity(finalIfcOpacity);
            var ifcSlider = document.getElementById('ifc-opacity');
            if (ifcSlider) ifcSlider.value = String(finalIfcOpacity);
            if (animFrame !== null) cancelAnimationFrame(animFrame);
            self._revealCleanup = null;
        }
        this._revealCleanup = cleanup;

        function step(now) {
            var elapsed = now - startTime;
            if (elapsed < fadeMs) {
                var t = elapsed / fadeMs;
                self.setIfcOpacity(1 - (1 - finalIfcOpacity) * easeOutCubic(t));
                animFrame = requestAnimationFrame(step);
                return;
            }
            if (self.ifcOpacity !== finalIfcOpacity) self.setIfcOpacity(finalIfcOpacity);
            if (elapsed < fadeMs + revealMs) {
                // Linear pace for the reveal: the plane climbs at a constant m/s, so a
                // 10 m building takes roughly twice as long as a 5 m one and the viewer
                // can actually follow the sweep instead of seeing only the slow tail of
                // easeOutCubic.
                var t2 = Math.max(0, Math.min(1, (elapsed - fadeMs) / revealMs));
                revealPlane.constant = yMin + (yMax - yMin) * t2;
                animFrame = requestAnimationFrame(step);
                return;
            }
            cleanup();
            onComplete();
        }

        animFrame = requestAnimationFrame(step);
    };

    SceneViewer.prototype.resetClipping = function () {
        if (!this.clipPlanes) return;
        for (var i = 0; i < this.clipPlanes.length; i += 1) {
            this.clipPlanes[i].constant = Infinity;
        }
        this.clipRanges = { xmin: -Infinity, xmax: Infinity, ymin: -Infinity, ymax: Infinity, zmin: -Infinity, zmax: Infinity };
        this.applyFdsClipVisibility();
    };

    // Used when the model came from the lightweight meta builder and doesn't carry IFC-native
    // bounds. Computes the world box from the freshly-added IFC group and frames it.
    SceneViewer.prototype.fitToWorldBox = function () {
        this.ifcGroup.updateMatrixWorld(true);
        var box = new THREE.Box3().expandByObject(this.ifcGroup);
        if (box.isEmpty()) return;
        var center = box.getCenter(new THREE.Vector3());
        var size = box.getSize(new THREE.Vector3());
        var span = Math.max(size.x, size.y, size.z, 1);
        this.walkFloorY = box.min.y;
        this.controls.target.copy(center);
        this.camera.position.set(center.x + span * 1.2, center.y + span * 0.9, center.z + span * 1.2);
        this.camera.near = Math.max(span / 200, 0.05);
        this.camera.far = span * 50;
        this.camera.updateProjectionMatrix();
        this.controls.update();
    };

    // Mounts geometry produced by the web-ifc WASM engine. Walls/slabs come pre-cut around
    // their window/door openings (web-ifc applies IfcRelVoidsElement booleans natively), so
    // the preview shows real voids. web-ifc converts IFC Z-up to Three Y-up with Rx(-90°)
    // (a rotation), while the rest of the scene goes through toThree() (a Y/Z swap, i.e. a
    // mirror). The two differ only in the sign of the depth axis, so a Z-flip on the web-ifc
    // matrices is enough to land them in the same world space as the FDS overlay.
    SceneViewer.prototype.addWebIfcDisplayMeshes = function (model, displayMeshes) {
        var elementsByExpressID = {};
        (model.elements || []).forEach(function (el) { elementsByExpressID[el.stepId] = el; });

        var zFlip = new THREE.Matrix4().set(
            1, 0, 0, 0,
            0, 1, 0, 0,
            0, 0, -1, 0,
            0, 0, 0, 1
        );
        var self = this;

        displayMeshes.forEach(function (entry) {
            var element = elementsByExpressID[entry.expressID];
            var group = (element && element.reference === true) ? self.ifcReferenceGroup : self.ifcSolidGroup;

            var geom = new THREE.BufferGeometry();
            geom.setAttribute('position', new THREE.BufferAttribute(entry.positions, 3));
            geom.setAttribute('normal', new THREE.BufferAttribute(entry.normals, 3));
            geom.setIndex(new THREE.BufferAttribute(entry.indices, 1));

            var ifcType = element ? element.ifcType : null;
            var style = styleForIfcType(ifcType, element && element.convertible === false, entry.color);
            var opacity = scaleIfcOpacity(style.opacity, self.ifcOpacity);
            var isTransparent = opacity < 1;

            var material = new THREE.MeshPhongMaterial({
                color: style.color,
                transparent: isTransparent,
                opacity: opacity,
                side: THREE.DoubleSide,
                depthWrite: true,
                shininess: 8,
                specular: 0x0b0b0b
            });
            material.userData.ifcBaseOpacity = style.opacity;
            material.userData.isIfcFace = true;
            material.userData.isIfcOpeningSurface = !!style.openingSurface;

            var mesh = new THREE.Mesh(geom, material);
            var local = new THREE.Matrix4().fromArray(entry.matrix);
            mesh.matrixAutoUpdate = false;
            mesh.matrix.multiplyMatrices(zFlip, local);
            mesh.renderOrder = isTransparent ? 1 : 0;

            if (element) {
                mesh.userData = {
                    type: 'IFC',
                    id: element.name || element.ifcType + ' #' + element.stepId,
                    ifcType: element.ifcType,
                    ifcCategory: categoryForIfcType(element.ifcType),
                    globalId: element.globalId,
                    convertible: element.convertible,
                    fdsRole: element.fdsRole,
                    canExportAsSolid: element.canExportAsSolid,
                    conversionNote: element.conversionNote,
                    bounds: element.bounds,
                    raw: element.raw
                };
            } else {
                mesh.userData = {
                    type: 'IFC',
                    id: 'IFC #' + entry.expressID,
                    ifcType: 'IFC',
                    ifcCategory: 'other',
                    expressID: entry.expressID
                };
            }

            var edgeMaterial = new THREE.LineBasicMaterial({
                color: style.edgeColor,
                transparent: true,
                opacity: scaleIfcOpacity(style.edgeOpacity, self.ifcOpacity),
                depthWrite: false
            });
            edgeMaterial.userData.ifcBaseOpacity = style.edgeOpacity;
            var edges = new THREE.LineSegments(
                new THREE.EdgesGeometry(geom, 50),
                edgeMaterial
            );
            edges.visible = style.openingSurface || self.showIfcEdges;
            edges._isIfcEdge = true;
            edges._isIfcOpeningEdge = !!style.openingSurface;
            edges.userData = mesh.userData;
            mesh.add(edges);

            group.add(mesh);
        });
    };

    SceneViewer.prototype.makeWireBox = function (item, color, type) {
        var size = sizeFromXb(item.xb, 0.001);
        var center = centerFromXb(item.xb);
        var geometry = new THREE.BoxGeometry(size.x, size.z, size.y);
        var edges = new THREE.EdgesGeometry(geometry);
        var material = new THREE.LineBasicMaterial({ color: color, transparent: true, opacity: 0.9 });
        var line = new THREE.LineSegments(edges, material);
        line.position.copy(toThree(center.x, center.y, center.z));
        line.userData = makeUserData(type, item);
        return line;
    };

    SceneViewer.prototype.makeBox = function (item, fallbackColor, type, forceThin) {
        var size = sizeFromXb(item.xb, forceThin ? 0.025 : 0.001);
        var center = centerFromXb(item.xb);
        var color = item.color ? rgbToHex(item.color) : fallbackColor;
        // Window/door closures sit exactly on the host wall plane, which causes z-fighting
        // flicker against the wall OBST behind them. Inflate the rendered geometry by ~6 mm
        // in each direction so the closure's faces sit slightly proud of the wall. The FDS
        // file data is unchanged — only the Three.js box is bumped.
        var isClosure = type === 'OBST' && (item.surf_id === 'IFC_WINDOW' || item.surf_id === 'IFC_DOOR');
        if (isClosure) {
            size.x += 0.012;
            size.y += 0.012;
            size.z += 0.012;
        }
        var geometry = new THREE.BoxGeometry(size.x, size.z, size.y);
        // HOLEs are "negative" entities (they carve blocking from a prior &OBST). When the
        // user also has Closed window/door fills on, a colored closure OBST sits in the same
        // volume — drawing the HOLE solid would mask the closure's IFC_WINDOW / IFC_DOOR
        // colour. Render HOLEs very transparent and depthWrite-off so the closure shows
        // through, but keep the edges visible so the user can still see which volumes are
        // declared as HOLEs.
        var faceOpacity;
        if (type === 'OBST') faceOpacity = this.opacity;
        else if (type === 'HOLE') faceOpacity = 0.18;
        else faceOpacity = 0.82;
        var material = new THREE.MeshPhongMaterial({
            color: color,
            transparent: true,
            opacity: faceOpacity,
            side: THREE.DoubleSide,
            depthWrite: type !== 'HOLE'
        });
        var box = new THREE.Mesh(geometry, material);
        box.position.copy(toThree(center.x, center.y, center.z));
        box.userData = makeUserData(type, item);
        if (type === 'HOLE') box.renderOrder = 2;

        var edgeMaterial = new THREE.LineBasicMaterial({
            color: type === 'HOLE' ? 0x00b3cc : 0x4d5264,
            transparent: true,
            opacity: type === 'HOLE' ? 0.85 : 0.55
        });
        var edges = new THREE.LineSegments(new THREE.EdgesGeometry(geometry), edgeMaterial);
        edges.userData = box.userData;
        box.add(edges);
        return box;
    };

    SceneViewer.prototype.makeGeom = function (geom) {
        if (geom.type === 'sphere') {
            var sphereGeometry = new THREE.SphereGeometry(geom.radius, 24, 14);
            var sphereMaterial = new THREE.MeshPhongMaterial({ color: geom.color ? rgbToHex(geom.color) : 0x64c8ff, transparent: true, opacity: this.opacity });
            var sphere = new THREE.Mesh(sphereGeometry, sphereMaterial);
            sphere.position.copy(toThree(geom.origin[0], geom.origin[1], geom.origin[2]));
            sphere.userData = makeUserData('GEOM sphere', geom);
            return sphere;
        }

        var positions = [];
        var indices = [];
        geom.vertices.forEach(function (v) {
            var converted = toThree(v[0], v[1], v[2]);
            positions.push(converted.x, converted.y, converted.z);
        });
        geom.faces.forEach(function (f) { indices.push(f[0], f[1], f[2]); });

        var geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
        geometry.setIndex(indices);
        geometry.computeVertexNormals();

        // GEOMs render distinctly darker than OBSTs so the two outputs are easy to tell
        // apart in the overlay. Most GEOMs are SURF_ID='IFC_SOLID' (RGB 185 gray); the 0.55
        // multiplier drops them to ~102 gray (about 45% darker), past the threshold where
        // Phong lighting could be mistaken for the lit/shadowed side of an OBST.
        var baseColor = geom.color ? rgbToHex(geom.color) : 0x707078;
        var material = new THREE.MeshPhongMaterial({
            color: darkenHex(baseColor, 0.55),
            transparent: true,
            opacity: this.opacity,
            side: THREE.DoubleSide
        });
        var mesh = new THREE.Mesh(geometry, material);
        mesh.userData = makeUserData('GEOM', geom);
        var edges = new THREE.LineSegments(
            new THREE.EdgesGeometry(geometry, 25),
            new THREE.LineBasicMaterial({ color: 0x1d6f9c, transparent: true, opacity: 0.7 })
        );
        edges.userData = mesh.userData;
        mesh.add(edges);
        return mesh;
    };

    SceneViewer.prototype.makeIfcElement = function (element) {
        var positions = [];
        var indices = [];
        // Prefer the display mesh (host walls carry their window/door voids there); the
        // solid element.mesh is reserved for the FDS export pipeline.
        var source = element.displayMesh || element.mesh;
        source.vertices.forEach(function (v) {
            var converted = toThree(v[0], v[1], v[2]);
            positions.push(converted.x, converted.y, converted.z);
        });
        source.faces.forEach(function (f) {
            indices.push(f[0], f[1], f[2]);
        });

        var geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
        geometry.setIndex(indices);
        geometry.computeVertexNormals();

        var style = styleForIfcType(element.ifcType, element.convertible === false);
        var opacity = scaleIfcOpacity(style.opacity, this.ifcOpacity);
        var isTransparent = opacity < 1;
        var material = new THREE.MeshPhongMaterial({
            color: style.color,
            transparent: isTransparent,
            opacity: opacity,
            side: THREE.DoubleSide,
            depthWrite: true,
            shininess: 8,
            specular: 0x0b0b0b
        });
        material.userData.ifcBaseOpacity = style.opacity;
        material.userData.isIfcFace = true;
        material.userData.isIfcOpeningSurface = !!style.openingSurface;
        var mesh = new THREE.Mesh(geometry, material);
        mesh.renderOrder = isTransparent ? 1 : 0;
        mesh.userData = {
            type: 'IFC',
            id: element.name || element.ifcType + ' #' + element.stepId,
            ifcType: element.ifcType,
            ifcCategory: categoryForIfcType(element.ifcType),
            globalId: element.globalId,
            convertible: element.convertible,
            fdsRole: element.fdsRole,
            canExportAsSolid: element.canExportAsSolid,
            conversionNote: element.conversionNote,
            bounds: element.bounds,
            raw: element.raw
        };

        var edgeMaterial = new THREE.LineBasicMaterial({
            color: style.edgeColor,
            transparent: true,
            opacity: scaleIfcOpacity(style.edgeOpacity, this.ifcOpacity),
            depthWrite: false
        });
        edgeMaterial.userData.ifcBaseOpacity = style.edgeOpacity;
        var edges = new THREE.LineSegments(
            new THREE.EdgesGeometry(geometry, 50),
            edgeMaterial
        );
        edges.visible = style.openingSurface || this.showIfcEdges;
        edges._isIfcEdge = true;
        edges._isIfcOpeningEdge = !!style.openingSurface;
        edges.userData = mesh.userData;
        mesh.add(edges);
        return mesh;
    };

    SceneViewer.prototype.setViewMode = function (mode) {
        this.viewMode = mode;
        this.syncRootLayerVisibility();
    };

    SceneViewer.prototype.setNavigationModeChangeHandler = function (handler) {
        this.onNavigationModeChange = handler || function () {};
    };

    SceneViewer.prototype.setNavigationMode = function (mode) {
        var nextMode = mode === 'walk' && this.walkControls ? 'walk' : 'orbit';
        if (nextMode === this.navigationMode) {
            if (nextMode === 'walk' && this.walkPlaced && !this.walkControls.isLocked) this.walkControls.lock();
            return;
        }

        this.navigationMode = nextMode;
        this.controls.enabled = nextMode === 'orbit';
        this.clearWalkMovement();
        this.walkVelocityY = 0;
        this.container.classList.toggle('is-walking', nextMode === 'walk');
        this.container.classList.toggle('is-walk-awaiting', nextMode === 'walk');
        this.container.classList.remove('is-walk-placed');
        this.clearHover();

        if (nextMode === 'walk') {
            this.walkSavedCamera = {
                position: this.camera.position.clone(),
                quaternion: this.camera.quaternion.clone(),
                target: this.controls.target.clone()
            };
            this.walkPlaced = false;
            this.setWalkStatus('Click a floor or stair surface to begin.');
        } else {
            if (this.walkControls.isLocked) this.walkControls.unlock();
            this.walkPlaced = false;
            if (this.walkSavedCamera) {
                this.camera.position.copy(this.walkSavedCamera.position);
                this.camera.quaternion.copy(this.walkSavedCamera.quaternion);
                this.controls.target.copy(this.walkSavedCamera.target);
                this.walkSavedCamera = null;
                this.controls.update();
            } else {
                this.syncOrbitTargetToCamera();
            }
            this.setWalkStatus('');
        }
        this.onNavigationModeChange(nextMode);
    };

    SceneViewer.prototype.positionWalkCamera = function () {
        var lookDirection = this.camera.getWorldDirection(new THREE.Vector3());
        lookDirection.y = 0;
        if (lookDirection.lengthSq() < 1e-8) lookDirection.set(0, 0, -1);
        lookDirection.normalize();

        var target = this.controls.target.clone();
        var horizontalDistance = Math.max(3, Math.hypot(
            this.camera.position.x - target.x,
            this.camera.position.z - target.z
        ));
        this.camera.position.set(
            target.x - lookDirection.x * horizontalDistance,
            this.walkFloorY + this.walkEyeHeight,
            target.z - lookDirection.z * horizontalDistance
        );
        this.camera.lookAt(new THREE.Vector3(target.x, this.camera.position.y, target.z));
    };

    SceneViewer.prototype.syncOrbitTargetToCamera = function () {
        var direction = this.camera.getWorldDirection(new THREE.Vector3());
        this.controls.target.copy(this.camera.position).add(direction.multiplyScalar(5));
        this.controls.update();
    };

    SceneViewer.prototype.handleWalkUnlock = function () {
        if (this.navigationMode === 'walk') this.setNavigationMode('orbit');
    };

    SceneViewer.prototype.handleWalkKey = function (pressed, event) {
        if (this.navigationMode !== 'walk') return;
        var key = String(event.key || '').toLowerCase();
        var handled = true;
        if (key === 'w' || key === 'arrowup') this.walkMovement.forward = pressed;
        else if (key === 's' || key === 'arrowdown') this.walkMovement.backward = pressed;
        else if (key === 'a' || key === 'arrowleft') this.walkMovement.left = pressed;
        else if (key === 'd' || key === 'arrowright') this.walkMovement.right = pressed;
        else if (key === ' ') this.walkMovement.jump = pressed;
        else if (key === 'shift') this.walkMovement.fast = pressed;
        else handled = false;
        if (handled) event.preventDefault();
    };

    SceneViewer.prototype.clearWalkMovement = function () {
        Object.keys(this.walkMovement).forEach(function (key) {
            this.walkMovement[key] = false;
        }, this);
    };

    SceneViewer.prototype.updateWalkMovement = function (delta) {
        if (!this.walkPlaced || !delta) return;

        var forward = this.camera.getWorldDirection(new THREE.Vector3());
        forward.y = 0;
        if (forward.lengthSq() < 1e-9) forward.set(0, 0, -1);
        forward.normalize();
        var right = new THREE.Vector3().crossVectors(forward, new THREE.Vector3(0, 1, 0)).normalize();
        var move = new THREE.Vector3();

        if (this.walkMovement.forward) move.add(forward);
        if (this.walkMovement.backward) move.sub(forward);
        if (this.walkMovement.right) move.add(right);
        if (this.walkMovement.left) move.sub(right);
        if (move.lengthSq()) {
            move.normalize().multiplyScalar(this.walkSpeed * (this.walkMovement.fast ? this.walkRunMultiplier : 1) * delta);
        }

        var cameraPosition = this.camera.position;
        var horizontal = this.resolveWalkHorizontal(cameraPosition, cameraPosition.x + move.x, cameraPosition.z + move.z);
        var currentFloorY = cameraPosition.y - this.walkEyeHeight;
        var floorY = this.walkRaycastDown(horizontal.x, horizontal.z, cameraPosition.y + this.walkStepHeight + 0.05);
        var surfaceY = floorY !== null && floorY <= currentFloorY + this.walkStepHeight + 0.02
            ? floorY
            : this.walkDomainFloor();
        var targetEyeY = surfaceY + this.walkEyeHeight;

        this.walkVelocityY -= this.walkGravity * delta;
        var nextY = cameraPosition.y + this.walkVelocityY * delta;
        if (nextY <= targetEyeY) {
            nextY = targetEyeY;
            this.walkVelocityY = 0;
            if (this.walkMovement.jump) this.walkVelocityY = 4;
        }

        this.camera.position.set(horizontal.x, nextY, horizontal.z);
    };

    SceneViewer.prototype.walkCollisionTargets = function () {
        var targets = [];
        var hasFdsSolids = this.obstGroup.children.length || this.geomGroup.children.length;
        if (hasFdsSolids) {
            collectWalkTargets(this.obstGroup, targets);
            collectWalkTargets(this.geomGroup, targets);
        } else {
            collectWalkTargets(this.ifcSolidGroup, targets, function (node) {
                return node.userData.ifcType !== 'IFCDOOR' && node.userData.ifcType !== 'IFCWINDOW';
            });
        }
        return targets;
    };

    SceneViewer.prototype.walkDomainFloor = function () {
        return Number.isFinite(this.walkFloorY) ? this.walkFloorY : 0;
    };

    SceneViewer.prototype.walkRaycastDown = function (x, z, fromY) {
        this.scene.updateMatrixWorld(true);
        this.walkRaycaster.set(new THREE.Vector3(x, fromY, z), new THREE.Vector3(0, -1, 0));
        this.walkRaycaster.far = 200;
        var hits = this.walkRaycaster.intersectObjects(this.walkCollisionTargets(), false);
        for (var index = 0; index < hits.length; index += 1) {
            if (walkHitHasUpwardNormal(hits[index], 0.2)) return hits[index].point.y;
        }
        return null;
    };

    SceneViewer.prototype.resolveWalkHorizontal = function (from, toX, toZ) {
        var dx = toX - from.x;
        var dz = toZ - from.z;
        var stepLength = Math.hypot(dx, dz);
        if (stepLength < 1e-6) return { x: from.x, z: from.z };

        this.scene.updateMatrixWorld(true);
        var direction = new THREE.Vector3(dx / stepLength, 0, dz / stepLength);
        var probeYs = [from.y, from.y - this.walkEyeHeight * 0.5];
        var targets = this.walkCollisionTargets();
        var holeBoxes = this.walkHoleBboxes();
        var minimumHit = Infinity;

        probeYs.forEach(function (probeY) {
            this.walkRaycaster.set(new THREE.Vector3(from.x, probeY, from.z), direction);
            this.walkRaycaster.far = stepLength + this.walkRadius;
            var hits = this.walkRaycaster.intersectObjects(targets, false);
            // First passable hit wins. Skip:
            //  * Door closure OBSTs (IFC_DOOR SURF) — the door is openable, walk through it.
            //  * Wall OBST hits whose hit point falls inside any &HOLE volume — the HOLE
            //    declares that this region of the wall is carved away in the FDS namelist,
            //    so the walker should pass straight through it in the viewer too.
            for (var i = 0; i < hits.length; i += 1) {
                if (walkHitIsPassable(hits[i], holeBoxes)) continue;
                if (hits[i].distance < minimumHit) minimumHit = hits[i].distance;
                break;
            }
        }, this);

        var allowed = minimumHit < Infinity ? Math.max(0, minimumHit - this.walkRadius) : stepLength;
        return {
            x: from.x + direction.x * allowed,
            z: from.z + direction.z * allowed
        };
    };

    // Builds a cached list of HOLE world-space bboxes for the current walk step. Called
    // once per movement update so each individual ray cast can reuse it.
    SceneViewer.prototype.walkHoleBboxes = function () {
        var boxes = [];
        if (!this.holeGroup || !this.holeGroup.visible) return boxes;
        this.holeGroup.updateMatrixWorld(true);
        this.holeGroup.children.forEach(function (node) {
            if (!node.isMesh && !node.children.length) return;
            var box = new THREE.Box3().setFromObject(node);
            if (!box.isEmpty()) boxes.push(box);
        });
        return boxes;
    };

    SceneViewer.prototype.placeWalkerFromClick = function (clientX, clientY) {
        var rect = this.renderer.domElement.getBoundingClientRect();
        this.mouse.x = ((clientX - rect.left) / rect.width) * 2 - 1;
        this.mouse.y = -((clientY - rect.top) / rect.height) * 2 + 1;
        this.raycaster.setFromCamera(this.mouse, this.camera);
        this.scene.updateMatrixWorld(true);

        var hits = this.raycaster.intersectObjects(this.walkCollisionTargets(), false);
        // Previous logic placed the walker on the very first hit with an upward-facing
        // normal. That puts the walker on the *top* of whatever the cursor crossed first —
        // a wall's top capping face, a beam, a door header, or a thin door-closure OBST —
        // instead of on the floor of the room the user is pointing at. Now we use the
        // closest hit only as an (x, z) target, then raycast straight DOWN from above to
        // find the actual walkable floor below that point.
        if (hits.length) {
            var anchor = hits[0].point.clone();
            var startY = anchor.y + 50; // well above any reasonable building height
            var floorY = this.walkRaycastDown(anchor.x, anchor.z, startY);
            if (floorY !== null) {
                this.placeWalkerAt(new THREE.Vector3(anchor.x, floorY, anchor.z));
                return true;
            }
            // Fallback: drop to the model's natural floor extent.
            this.placeWalkerAt(new THREE.Vector3(anchor.x, this.walkDomainFloor(), anchor.z));
            return true;
        }

        var direction = this.raycaster.ray.direction;
        if (direction.y < -1e-6) {
            var distance = (this.walkDomainFloor() - this.raycaster.ray.origin.y) / direction.y;
            if (distance > 0) {
                this.placeWalkerAt(this.raycaster.ray.origin.clone().add(direction.clone().multiplyScalar(distance)));
                return true;
            }
        }

        this.setWalkStatus('No walkable surface there. Click a floor or stair.');
        return false;
    };

    SceneViewer.prototype.placeWalkerAt = function (point) {
        var eye = new THREE.Vector3(point.x, point.y + this.walkEyeHeight, point.z);
        var direction = this.camera.getWorldDirection(new THREE.Vector3());
        direction.y = 0;
        if (direction.lengthSq() < 1e-9) direction.set(0, 0, -1);
        direction.normalize();

        this.camera.position.copy(eye);
        this.camera.lookAt(eye.clone().add(direction));
        this.walkPlaced = true;
        this.walkVelocityY = 0;
        this.container.classList.remove('is-walk-awaiting');
        this.container.classList.add('is-walk-placed');
        this.setWalkStatus('Walking');
        if (!this.walkControls.isLocked) this.walkControls.lock();
    };

    SceneViewer.prototype.setWalkStatus = function (text) {
        var hud = document.getElementById('walk-hud');
        var status = document.getElementById('walk-hud-status');
        if (!hud || !status) return;
        status.textContent = text;
        hud.hidden = !text;
    };

    SceneViewer.prototype.setTheme = function (theme) {
        this.theme = theme === 'dark' ? 'dark' : 'light';
        this.scene.background.setHex(this.theme === 'dark' ? 0x1a1a2e : 0xf4f5f8);
        this.applyGroundGridTheme();
    };

    SceneViewer.prototype.applyGroundGridTheme = function () {
        if (!this.groundGrid || !this.groundGrid.geometry) return;
        var colors = this.groundGrid.geometry.getAttribute('color');
        if (!colors) return;

        var major = new THREE.Color(this.theme === 'dark' ? 0x506080 : 0xa9afbd);
        var minor = new THREE.Color(this.theme === 'dark' ? 0x26334d : 0xd8dae2);
        var lineCount = colors.count / 4;
        var center = Math.floor(lineCount / 2);
        for (var line = 0; line < lineCount; line += 1) {
            var color = line === center ? major : minor;
            for (var vertex = 0; vertex < 4; vertex += 1) {
                colors.setXYZ(line * 4 + vertex, color.r, color.g, color.b);
            }
        }
        colors.needsUpdate = true;
        this.groundGrid.material.opacity = this.theme === 'dark' ? 0.34 : 0.42;
    };

    SceneViewer.prototype.setLayerVisible = function (layer, visible) {
        if (layer === 'ifcEdges') {
            this.setIfcEdgesVisible(visible);
            return;
        }
        var map = {
            meshes: this.meshGroup,
            obsts: this.obstGroup,
            vents: this.ventGroup,
            holes: this.holeGroup,
            geoms: this.geomGroup,
            ifcReference: this.ifcReferenceGroup,
            groundGrid: this.groundGrid
        };
        if (map[layer]) map[layer].visible = visible;
    };

    SceneViewer.prototype.setIfcEdgesVisible = function (visible) {
        this.showIfcEdges = !!visible;
        [this.ifcSolidGroup, this.ifcReferenceGroup].forEach(function (group) {
            group.traverse(function (node) {
                if (node._isIfcEdge) node.visible = node._isIfcOpeningEdge || !!visible;
            });
        });
    };

    // Tracks per-category visibility (structure/fills/other). Re-evaluated on every load and
    // on every checkbox toggle so meshes added later (web-ifc deferred swap) honor the state.
    SceneViewer.prototype.setIfcCategoryVisible = function (category, visible) {
        if (!this.ifcCategoryVisible) this.ifcCategoryVisible = { structure: true, fills: true, other: true };
        if (this.ifcCategoryVisible[category] === undefined) return;
        this.ifcCategoryVisible[category] = !!visible;
        this.applyIfcCategoryVisibility();
    };

    SceneViewer.prototype.applyIfcCategoryVisibility = function () {
        if (!this.ifcCategoryVisible) this.ifcCategoryVisible = { structure: true, fills: true, other: true };
        var categoryState = this.ifcCategoryVisible;
        var excludedSteps = this.excludedStepIds || {};
        var excludedItems = this.excludedItemIds || {};
        [this.ifcSolidGroup, this.ifcReferenceGroup].forEach(function (group) {
            group.children.forEach(function (mesh) {
                if (isExcludedMesh(mesh, excludedSteps, excludedItems)) { mesh.visible = false; return; }
                var category = mesh.userData && mesh.userData.ifcCategory;
                if (category && categoryState[category] === false) mesh.visible = false;
                else mesh.visible = true;
            });
        });
    };

    // Hides FDS / IFC meshes whose source IFC stepId is in the source-exclusion set OR whose
    // own primitive id is in the item-exclusion set. The first is the "delete the whole IFC
    // element" path; the second is the "delete just this OBST/GEOM box" path. Reapplies on
    // every load and on undo so toggling them on and off doesn't rebuild the scene.
    SceneViewer.prototype.setExclusions = function (stepIdMap, itemIdMap) {
        this.excludedStepIds = stepIdMap || {};
        this.excludedItemIds = itemIdMap || {};
        var excludedSteps = this.excludedStepIds;
        var excludedItems = this.excludedItemIds;
        [this.fdsGroup, this.obstGroup, this.ventGroup, this.holeGroup, this.geomGroup].forEach(function (group) {
            if (!group) return;
            group.children.forEach(function (mesh) {
                mesh.visible = !isExcludedMesh(mesh, excludedSteps, excludedItems);
            });
        });
        this.applyIfcCategoryVisibility();
    };

    SceneViewer.prototype.setFdsOpacity = function (opacity) {
        this.opacity = Math.max(0, Math.min(1, Number(opacity) || 0));
        if (this.opacity === 0) this.clearHover();

        var fdsOpacity = this.opacity;
        [this.meshGroup, this.obstGroup, this.ventGroup, this.geomGroup].forEach(function (group) {
            group.traverse(function (node) {
                if (node.material && node.material.opacity !== undefined) {
                    node.material.opacity = fdsOpacity;
                    node.material.transparent = true;
                }
            });
        });
        this.syncRootLayerVisibility();
    };

    SceneViewer.prototype.setIfcOpacity = function (opacity) {
        this.ifcOpacity = Math.max(0, Math.min(1, Number(opacity) || 0));
        this.clearHover();

        var ifcOpacity = this.ifcOpacity;
        [this.ifcSolidGroup, this.ifcReferenceGroup].forEach(function (group) {
            group.traverse(function (node) {
                setIfcMaterialOpacity(node.material, ifcOpacity);
                if (node.isMesh && node.userData && node.userData.type === 'IFC') {
                    node.renderOrder = ifcOpacity < 1 ? 1 : 0;
                }
            });
        });
        this.syncRootLayerVisibility();
    };

    SceneViewer.prototype.syncRootLayerVisibility = function () {
        this.fdsGroup.visible = this.viewMode !== 'ifc' && this.opacity > 0;
        this.ifcGroup.visible = this.viewMode !== 'fds' && this.ifcOpacity > 0;
    };

    SceneViewer.prototype.fitToBounds = function (bounds) {
        if (!bounds) return;
        this.walkFloorY = bounds.zmin;
        var center = {
            x: (bounds.xmin + bounds.xmax) / 2,
            y: (bounds.ymin + bounds.ymax) / 2,
            z: (bounds.zmin + bounds.zmax) / 2
        };
        var span = Math.max(bounds.xmax - bounds.xmin, bounds.ymax - bounds.ymin, bounds.zmax - bounds.zmin, 1);
        var threeCenter = toThree(center.x, center.y, center.z);
        this.controls.target.copy(threeCenter);
        this.camera.position.set(threeCenter.x + span * 1.2, threeCenter.y + span * 0.9, threeCenter.z + span * 1.2);
        this.camera.near = Math.max(span / 200, 0.05);
        this.camera.far = span * 50;
        this.camera.updateProjectionMatrix();
        this.controls.update();
    };

    SceneViewer.prototype.resetCamera = function () {
        this.setNavigationMode('orbit');
        var box = new THREE.Box3();
        if (this.fdsGroup.visible) box.expandByObject(this.fdsGroup);
        if (this.ifcGroup.visible) box.expandByObject(this.ifcGroup);
        if (box.isEmpty()) {
            box.expandByObject(this.fdsGroup);
            box.expandByObject(this.ifcGroup);
        }
        if (!box.isEmpty()) {
            var center = box.getCenter(new THREE.Vector3());
            var size = box.getSize(new THREE.Vector3());
            var span = Math.max(size.x, size.y, size.z, 1);
            this.controls.target.copy(center);
            this.camera.position.set(center.x + span * 1.2, center.y + span * 0.9, center.z + span * 1.2);
            this.controls.update();
        }
    };

    // Shift+drag starts a marquee selection that picks every visible IFC / OBST / GEOM mesh
    // whose bbox-center projects inside the rectangle. A pure Shift+click (no movement past
    // MARQUEE_MIN_DRAG_PX) still falls through to handleClick so add-to-selection works.
    SceneViewer.prototype.handlePointerDown = function (event) {
        if (event.button !== 0 || !event.shiftKey) return;
        if (this.navigationMode === 'walk') return;
        var rect = this.renderer.domElement.getBoundingClientRect();
        this.marqueeState = {
            startX: event.clientX,
            startY: event.clientY,
            rect: rect,
            dragged: false,
            pointerId: event.pointerId
        };
        try { this.renderer.domElement.setPointerCapture(event.pointerId); } catch (_) { /* ignore */ }
        this.controls.enabled = false;
        event.preventDefault();
    };

    SceneViewer.prototype.handlePointerUp = function (event) {
        if (!this.marqueeState || event.pointerId !== this.marqueeState.pointerId) return;
        var state = this.marqueeState;
        this.marqueeState = null;
        this.controls.enabled = true;
        if (this.marqueeEl) this.marqueeEl.hidden = true;
        try { this.renderer.domElement.releasePointerCapture(event.pointerId); } catch (_) { /* ignore */ }
        if (!state.dragged) return; // Treated as a Shift+click — let handleClick add to selection.
        var rect = state.rect;
        var x1 = state.startX - rect.left;
        var y1 = state.startY - rect.top;
        var x2 = event.clientX - rect.left;
        var y2 = event.clientY - rect.top;
        this.completeMarqueeSelection(
            Math.min(x1, x2), Math.min(y1, y2),
            Math.max(x1, x2), Math.max(y1, y2)
        );
    };

    SceneViewer.prototype.updateMarqueeRectFromPointer = function (event) {
        var state = this.marqueeState;
        if (!state) return;
        var dx = event.clientX - state.startX;
        var dy = event.clientY - state.startY;
        if (!state.dragged) {
            if (Math.abs(dx) + Math.abs(dy) < 4) return; // MARQUEE_MIN_DRAG_PX
            state.dragged = true;
            if (this.marqueeEl) this.marqueeEl.hidden = false;
        }
        if (!this.marqueeEl) return;
        var rect = state.rect;
        var left = Math.min(state.startX, event.clientX) - rect.left;
        var top = Math.min(state.startY, event.clientY) - rect.top;
        this.marqueeEl.style.left = left + 'px';
        this.marqueeEl.style.top = top + 'px';
        this.marqueeEl.style.width = Math.abs(dx) + 'px';
        this.marqueeEl.style.height = Math.abs(dy) + 'px';
    };

    SceneViewer.prototype.completeMarqueeSelection = function (x1, y1, x2, y2) {
        var canvas = this.renderer.domElement;
        var width = canvas.clientWidth || 1;
        var height = canvas.clientHeight || 1;
        var targets = [];
        if (this.ifcOpacity > 0) collectVisiblePickTargets(this.ifcGroup, targets);
        if (this.opacity > 0) collectVisiblePickTargets(this.fdsGroup, targets);
        this.scene.updateMatrixWorld(true);
        var camera = this.camera;
        var picked = [];
        var bbox = new THREE.Box3();
        var centre = new THREE.Vector3();
        for (var i = 0; i < targets.length; i += 1) {
            var mesh = targets[i];
            var selectable = findSelectableNode(mesh);
            if (!selectable || !selectable.userData || !selectable.userData.type) continue;
            bbox.makeEmpty().expandByObject(mesh);
            if (bbox.isEmpty()) continue;
            bbox.getCenter(centre);
            centre.project(camera);
            if (centre.z < -1 || centre.z > 1) continue;
            var sx = (centre.x * 0.5 + 0.5) * width;
            var sy = (-centre.y * 0.5 + 0.5) * height;
            if (sx < x1 || sx > x2 || sy < y1 || sy > y2) continue;
            if (picked.indexOf(selectable) === -1) picked.push(selectable);
        }
        this.setSelectedObjects(picked);
        this.onSelect(picked.map(function (object) { return object.userData; }));
    };

    SceneViewer.prototype.handleClick = function (event) {
        if (this.navigationMode === 'walk') {
            if (!this.walkPlaced) this.placeWalkerFromClick(event.clientX, event.clientY);
            else if (!this.walkControls.isLocked) this.walkControls.lock();
            return;
        }
        var candidate = this.pickCandidate(event.clientX, event.clientY);
        var additive = event.shiftKey || event.ctrlKey || event.metaKey;
        this.selectObject(candidate ? candidate.object : null, additive);
        this.onSelect(this.selectedObjects.map(function (object) { return object.userData; }));
    };

    SceneViewer.prototype.handlePointerMove = function (event) {
        if (this.marqueeState) {
            this.updateMarqueeRectFromPointer(event);
            return;
        }
        if (this.navigationMode === 'walk') {
            this.clearHover();
            return;
        }
        var candidate = this.pickCandidate(event.clientX, event.clientY);
        var object = candidate ? candidate.object : null;

        if (object !== this.hoveredObject) {
            this.setHoveredObject(object);
        }

        if (candidate) {
            this.container.classList.add('is-picking');
            this.showTooltip(candidate.data, event.clientX, event.clientY);
        } else {
            this.container.classList.remove('is-picking');
            this.hideTooltip();
        }
    };

    SceneViewer.prototype.pickCandidate = function (clientX, clientY) {
        var rect = this.renderer.domElement.getBoundingClientRect();
        this.mouse.x = ((clientX - rect.left) / rect.width) * 2 - 1;
        this.mouse.y = -((clientY - rect.top) / rect.height) * 2 + 1;
        this.raycaster.setFromCamera(this.mouse, this.camera);

        var targets = [];
        if (this.opacity > 0) {
            collectVisiblePickTargets(this.fdsGroup, targets);
        }
        if (this.ifcOpacity > 0) {
            collectVisiblePickTargets(this.ifcGroup, targets);
        }

        var hits = this.raycaster.intersectObjects(targets, true);
        var seen = [];
        var candidates = hits
            .map(function (hit) {
                var object = findSelectableNode(hit.object);
                return {
                    distance: hit.distance,
                    object: object,
                    data: object ? object.userData : null
                };
            })
            .filter(function (candidate) {
                if (!candidate.object || !candidate.data || !candidate.data.type) return false;
                if (seen.indexOf(candidate.object) >= 0) return false;
                seen.push(candidate.object);
                return true;
            });

        candidates.sort(function (a, b) {
            // Distance-first so a click on the front wall picks the front wall, not a
            // HOLE / VENT / GEOM hiding behind it. Priority is only used as a tie-breaker
            // when two hits are within ~0.3 m of each other — that's the original case
            // priority was designed for (a VENT marker coincident with the OBST it sits on,
            // a HOLE rectangle overlapping a wall it carves into).
            var distGap = a.distance - b.distance;
            if (Math.abs(distGap) > 0.3) return distGap;
            var byPriority = selectionPriority(a.data.type) - selectionPriority(b.data.type);
            if (byPriority) return byPriority;
            // When two IFC hits are nearly the same distance, prefer the opaque one — clicking
            // through a window's glass should land on the wall behind, not on the glass itself.
            if (a.data.type === 'IFC' && b.data.type === 'IFC' && Math.abs(a.distance - b.distance) < 0.6) {
                var ao = isOpaqueIfcHit(a.object) ? 0 : 1;
                var bo = isOpaqueIfcHit(b.object) ? 0 : 1;
                if (ao !== bo) return ao - bo;
            }
            return distGap;
        });

        return candidates.length ? candidates[0] : null;
    };

    SceneViewer.prototype.setHoveredObject = function (object) {
        if (this.hoveredObject) setObjectHover(this.hoveredObject, false);
        this.hoveredObject = object || null;
        if (this.hoveredObject) setObjectHover(this.hoveredObject, true);
    };

    SceneViewer.prototype.selectObject = function (object, additive) {
        if (!additive) {
            this.setSelectedObjects(object ? [object] : []);
            return;
        }
        if (!object) return;

        var selectedObjects = this.selectedObjects.slice();
        var index = selectedObjects.indexOf(object);
        if (index >= 0) selectedObjects.splice(index, 1);
        else selectedObjects.push(object);
        this.setSelectedObjects(selectedObjects);
    };

    SceneViewer.prototype.setSelectedObjects = function (objects) {
        this.selectionHelpers.forEach(function (helper) {
            if (helper.parent) helper.parent.remove(helper);
            if (helper.geometry) helper.geometry.dispose();
            if (helper.material) helper.material.dispose();
        });
        this.selectionHelpers = [];
        this.selectedObjects = (objects || []).filter(function (object) {
            return object && object.geometry;
        });

        var self = this;
        this.selectedObjects.forEach(function (object) {
            self.selectionHelpers.push(self.makeSelectionHelper(object));
        });
    };

    SceneViewer.prototype.makeSelectionHelper = function (object) {
        var geometry = object.isLineSegments
            ? object.geometry.clone()
            : new THREE.EdgesGeometry(object.geometry, 15);
        var material = new THREE.LineBasicMaterial({
            color: 0xd63856,
            transparent: true,
            opacity: 1,
            depthTest: false
        });
        var helper = new THREE.LineSegments(geometry, material);
        helper.name = 'Selected object outline';
        // Mirror the object's full local transform via the matrix, not just PQS — web-ifc
        // meshes drive their placement through mesh.matrix directly (matrixAutoUpdate=false),
        // so position/quaternion/scale are stuck at defaults and copying them lands the
        // outline at the origin.
        if (object.matrixAutoUpdate) object.updateMatrix();
        helper.matrix.copy(object.matrix);
        helper.matrixAutoUpdate = false;
        helper.renderOrder = 1000;
        helper.raycast = function () {};
        object.parent.add(helper);
        return helper;
    };

    SceneViewer.prototype.clearHover = function () {
        this.setHoveredObject(null);
        this.container.classList.remove('is-picking');
        this.hideTooltip();
    };

    SceneViewer.prototype.showTooltip = function (data, clientX, clientY) {
        if (!this.tooltip || !data) return;

        var rect = this.container.getBoundingClientRect();
        var x = clientX - rect.left + 14;
        var y = clientY - rect.top + 14;
        var label = data.type + (data.id ? ': ' + data.id : '');

        this.tooltip.textContent = label;
        this.tooltip.hidden = false;

        var maxX = this.container.clientWidth - this.tooltip.offsetWidth - 10;
        var maxY = this.container.clientHeight - this.tooltip.offsetHeight - 10;
        this.tooltip.style.left = Math.max(10, Math.min(x, maxX)) + 'px';
        this.tooltip.style.top = Math.max(10, Math.min(y, maxY)) + 'px';
    };

    SceneViewer.prototype.hideTooltip = function () {
        if (this.tooltip) this.tooltip.hidden = true;
    };

    function clearGroup(group) {
        while (group.children.length) {
            var child = group.children.pop();
            child.traverse(function (node) {
                if (node.geometry) node.geometry.dispose();
                if (node.material) {
                    if (Array.isArray(node.material)) node.material.forEach(function (mat) { mat.dispose(); });
                    else node.material.dispose();
                }
            });
        }
    }

    function sizeFromXb(xb, minSize) {
        return {
            x: Math.max(xb[1] - xb[0], minSize),
            y: Math.max(xb[3] - xb[2], minSize),
            z: Math.max(xb[5] - xb[4], minSize)
        };
    }

    function centerFromXb(xb) {
        return {
            x: (xb[0] + xb[1]) / 2,
            y: (xb[2] + xb[3]) / 2,
            z: (xb[4] + xb[5]) / 2
        };
    }

    function toThree(x, y, z) {
        return new THREE.Vector3(x, z, y);
    }

    function rgbToHex(rgb) {
        return (rgb[0] << 16) + (rgb[1] << 8) + rgb[2];
    }

    // Multiply each RGB channel by `factor` (0..1) to darken a packed-int hex color. Used
    // to push GEOM materials a notch below their OBST siblings so the two output kinds are
    // visually distinct in the overlay.
    function darkenHex(hex, factor) {
        var f = Math.max(0, Math.min(1, factor));
        var r = Math.max(0, Math.min(255, Math.round(((hex >> 16) & 0xff) * f)));
        var g = Math.max(0, Math.min(255, Math.round(((hex >> 8) & 0xff) * f)));
        var b = Math.max(0, Math.min(255, Math.round((hex & 0xff) * f)));
        return (r << 16) | (g << 8) | b;
    }

    // Palette mirrors the standalone demo viewer: specific colors for the BIM staples (doors,
    // windows, walls, slabs, roofs, spaces) and the IFC-file's own surface color for anything
    // else when web-ifc supplied one.
    function styleForIfcType(type, referenceOnly, sourceColor) {
        if (type === 'IFCDOOR') {
            return { color: 0x985d3f, opacity: 1, edgeColor: 0x5a2c1d, edgeOpacity: 0.72, openingSurface: true };
        }
        if (type === 'IFCWINDOW') {
            return { color: 0x6db4d6, opacity: 0.62, edgeColor: 0x286c91, edgeOpacity: 0.72, openingSurface: true };
        }
        if (type === 'IFCSLAB' || type === 'IFCROOF') {
            return { color: 0xb7becb, opacity: 1, edgeColor: 0x5f6877, edgeOpacity: 0.72, openingSurface: false };
        }
        if (type === 'IFCWALL' || type === 'IFCWALLSTANDARDCASE') {
            return { color: 0xd2d6dc, opacity: 1, edgeColor: 0x67707d, edgeOpacity: 0.72, openingSurface: false };
        }
        if (type === 'IFCSPACE') {
            return { color: 0xa6d7c8, opacity: 0.18, edgeColor: 0x4b8b79, edgeOpacity: 0.5, openingSurface: false };
        }
        var fallback = sourceColor ? rgbColorToHex(sourceColor) : 0xc1c7d2;
        var fallbackOpacity = sourceColor && typeof sourceColor.a === 'number'
            ? Math.max(0.22, sourceColor.a)
            : 1;
        return {
            color: fallback,
            opacity: referenceOnly ? 0.45 : fallbackOpacity,
            edgeColor: 0x687184,
            edgeOpacity: 0.6,
            openingSurface: false
        };
    }

    function rgbColorToHex(color) {
        var r = Math.round(Math.max(0, Math.min(1, color.r)) * 255);
        var g = Math.round(Math.max(0, Math.min(1, color.g)) * 255);
        var b = Math.round(Math.max(0, Math.min(1, color.b)) * 255);
        return (r << 16) | (g << 8) | b;
    }

    function easeOutCubic(t) {
        return 1 - Math.pow(1 - Math.max(0, Math.min(1, t)), 3);
    }

    function categoryForIfcType(type) {
        if (!type) return 'other';
        if (type === 'IFCDOOR' || type === 'IFCWINDOW') return 'fills';
        if (/^IFC(WALL|SLAB|ROOF|COLUMN|BEAM|STAIR|MEMBER|RAILING|CURTAINWALL|PLATE|COVERING|FOOTING|PILE)/.test(type)) return 'structure';
        return 'other';
    }

    function isExcludedMesh(mesh, excludedSteps, excludedItems) {
        if (!mesh || !mesh.userData) return false;
        var userData = mesh.userData;
        if (excludedItems) {
            var itemIds = itemIdsForMesh(userData);
            for (var j = 0; j < itemIds.length; j += 1) {
                if (excludedItems[itemIds[j]]) return true;
            }
        }
        if (excludedSteps) {
            var stepIds = stepIdsForMesh(userData);
            for (var i = 0; i < stepIds.length; i += 1) {
                if (excludedSteps[stepIds[i]]) return true;
            }
        }
        return false;
    }

    function itemIdsForMesh(userData) {
        var ids = [];
        if (userData.id) ids.push(String(userData.id));
        if (userData.raw && userData.raw.ID) ids.push(String(userData.raw.ID));
        if (userData.ifcSource && userData.ifcSource.itemId) ids.push(String(userData.ifcSource.itemId));
        return ids;
    }

    function stepIdsForMesh(userData) {
        var ids = [];
        if (userData.ifcSource && userData.ifcSource.stepId) {
            ids.push(String(userData.ifcSource.stepId).replace(/^#/, ''));
        }
        if (userData.raw) {
            var raw = userData.raw;
            if (raw.id) ids.push(String(raw.id).replace(/^#/, ''));
            if (raw.stepId) ids.push(String(raw.stepId).replace(/^#/, ''));
            if (raw.__ifcSource && raw.__ifcSource.stepId) ids.push(String(raw.__ifcSource.stepId).replace(/^#/, ''));
        }
        if (userData.expressID) ids.push(String(userData.expressID));
        return ids;
    }

    function setIfcMaterialOpacity(material, ifcOpacity) {
        if (Array.isArray(material)) {
            material.forEach(function (item) { setIfcMaterialOpacity(item, ifcOpacity); });
            return;
        }
        if (!material || material.userData.ifcBaseOpacity === undefined) return;
        var opacity = scaleIfcOpacity(material.userData.ifcBaseOpacity, ifcOpacity);
        material.opacity = opacity;
        material.transparent = opacity < 1;
        if (material.userData.isIfcFace) {
            material.side = THREE.DoubleSide;
            material.depthWrite = true;
            material.needsUpdate = true;
        }
    }

    function scaleIfcOpacity(baseOpacity, ifcOpacity) {
        return Math.max(0, Math.min(1, baseOpacity * ifcOpacity));
    }

    function makeUserData(type, item) {
        return {
            type: type,
            id: item.id,
            surf_id: item.surf_id || null,
            ifcSource: item.ifcSource || null,
            xb: item.xb || null,
            raw: item.raw || item
        };
    }

    function findSelectableNode(object) {
        var node = object;
        var match = null;
        while (node) {
            if (node.userData && node.userData.type) match = node;
            node = node.parent;
        }
        return match;
    }

    function collectVisiblePickTargets(group, targets) {
        if (!group.visible) return;
        group.traverse(function (node) {
            if ((node.isMesh || node.isLineSegments) && isVisibleWithin(node, group)) targets.push(node);
        });
    }

    function collectWalkTargets(group, targets, predicate) {
        if (!group) return;
        group.traverse(function (node) {
            if (!node.isMesh || !node.visible) return;
            if (!predicate || predicate(node)) targets.push(node);
        });
    }

    function walkHitHasUpwardNormal(hit, minimumY) {
        if (!hit.face || !hit.object) return true;
        var normal = hit.face.normal.clone();
        normal.applyMatrix3(new THREE.Matrix3().getNormalMatrix(hit.object.matrixWorld)).normalize();
        return normal.y >= minimumY;
    }

    // Decides whether a horizontal walk-collision hit should be ignored, letting the walker
    // pass through:
    //  * Door closure OBSTs (SURF_ID='IFC_DOOR' in the FDS namelist) — doors are openable.
    //  * Wall sections that are carved away by a sibling &HOLE — the FDS-truth says there
    //    is no blocking at that location even though the mesh OBST geometry covers it.
    function walkHitIsPassable(hit, holeBoxes) {
        if (!hit || !hit.object) return false;
        var data = hit.object.userData;
        if (data && data.surf_id === 'IFC_DOOR') return true;
        if (!holeBoxes || !holeBoxes.length) return false;
        var pt = hit.point;
        for (var i = 0; i < holeBoxes.length; i += 1) {
            if (holeBoxes[i].containsPoint(pt)) return true;
        }
        return false;
    }

    function isVisibleWithin(node, root) {
        while (node) {
            if (!node.visible) return false;
            if (node === root) return true;
            node = node.parent;
        }
        return false;
    }

    function setObjectHover(object, hovered) {
        object.traverse(function (node) {
            if (node.material) setMaterialHover(node.material, hovered);
        });
    }

    function setMaterialHover(material, hovered) {
        if (Array.isArray(material)) {
            material.forEach(function (mat) { setMaterialHover(mat, hovered); });
            return;
        }

        if (!material) return;
        if (!material.userData.__hoverOriginal) {
            material.userData.__hoverOriginal = {
                color: material.color ? material.color.getHex() : null,
                emissive: material.emissive ? material.emissive.getHex() : null,
                opacity: material.opacity
            };
        }

        var original = material.userData.__hoverOriginal;
        if (hovered) {
            if (material.color) material.color.setHex(0xffd166);
            if (material.emissive) material.emissive.setHex(0x332000);
            if (material.opacity !== undefined) {
                material.opacity = Math.min(1, Math.max(material.opacity, 0.92));
                material.transparent = material.opacity < 1;
            }
        } else {
            if (material.color && original.color !== null) material.color.setHex(original.color);
            if (material.emissive && original.emissive !== null) material.emissive.setHex(original.emissive);
            if (material.opacity !== undefined) {
                material.opacity = original.opacity;
                material.transparent = material.opacity < 1;
            }
            delete material.userData.__hoverOriginal;
        }
    }

    function isOpaqueIfcHit(object) {
        if (!object || !object.material) return true;
        var material = object.material;
        var base = material.userData && material.userData.ifcBaseOpacity;
        if (typeof base === 'number') return base >= 0.95;
        return !material.transparent;
    }

    function selectionPriority(type) {
        if (type === 'VENT') return 1;
        if (type === 'HOLE') return 2;
        if (type === 'GEOM' || type === 'GEOM sphere') return 3;
        if (type === 'OBST') return 4;
        if (type === 'IFC') return 5;
        if (type === 'MESH') return 20;
        return 10;
    }

    ns.viewer.SceneViewer = SceneViewer;
})(window.IfcFds);
