// editor.js - Complete canvas functionality for sticker/flyer layout

console.log('Editor.js loaded');

// Inside your DOMContentLoaded event handler, add these debugging lines:
// Get layout data

const layoutDataElement = document.getElementById('layout-data');
console.log('Layout data element exists:', !!layoutDataElement);
if (layoutDataElement) {
    console.log('Raw layout data value:', layoutDataElement.value);
    console.log('First 100 characters:', layoutDataElement.value.substring(0, 100));
    console.log('First 5 character codes:',
        Array.from(layoutDataElement.value.substring(0, 5)).map(c => c.charCodeAt(0)));
    console.log('Value length:', layoutDataElement.value.length);
}
// const layoutData = JSON.parse(document.getElementById('layout-data').value);
const layoutData = window.layoutData;
// No parsing needed as it's already a JavaScript object
const layoutId = document.getElementById('layout-id').value;
const imageBase64 = document.getElementById('image-base64').value;

console.log('Layout data loaded:', {
    layoutId,
    paperWidth: layoutData.paper_width,
    paperHeight: layoutData.paper_height,
    stickerWidth: layoutData.sticker.width,
    stickerHeight: layoutData.sticker.height,
    margins: layoutData.margins,
    positions: layoutData.positions.length
});
console.log('Image base64 prefix:', imageBase64.substring(0, 50) + '...');



// Add a check for the canvas element
const canvasElement = document.getElementById('layout-canvas');
if (!canvasElement) {
    console.error('Canvas element not found!');
} else {
    console.log('Canvas element found:', {
        width: canvasElement.width,
        height: canvasElement.height
    });
}

// Check for Fabric.js
if (typeof fabric === 'undefined') {
    console.error('Fabric.js not loaded!');
} else {
    console.log('Fabric.js loaded:', fabric.version);
}









document.addEventListener('DOMContentLoaded', function () {
    // Advanced JSON parsing function
    function safeJSONParse(rawData) {
        try {
            // If it's already an object, return it
            if (typeof rawData === 'object') {
                return rawData;
            }

            // Replace single quotes with double quotes
            const jsonString = rawData
                .replace(/'/g, '"')  // Replace single quotes with double quotes
                .replace(/True/g, 'true')
                .replace(/False/g, 'false')
                .replace(/None/g, 'null')
                // Ensure keys are in double quotes
                .replace(/(\w+):/g, '"$1":')
                // Handle floating-point precision issues
                .replace(/(\d+\.\d+)00000000000002/g, '$1');

            return JSON.parse(jsonString);
        } catch (error) {
            console.error('JSON Parsing Error:', error);
            console.log('Problematic JSON String:', rawData);

            // Create a debug panel
            const debugPanel = document.createElement('div');
            debugPanel.style.cssText = `
                position: fixed;
                top: 10px;
                right: 10px;
                background: white;
                border: 2px solid red;
                padding: 15px;
                z-index: 9999;
                max-width: 400px;
                word-break: break-all;
            `;
            debugPanel.innerHTML = `
                <h3 style="color: red;">JSON Parsing Failed</h3>
                <pre>${rawData}</pre>
                <p>See console for detailed errors</p>
            `;
            document.body.appendChild(debugPanel);

            return null;
        }
    }

    // Get layout data from window variable
    if (!window.layoutData) {
        console.error('Layout data not available in window.layoutData!');
        return;
    }

    const layoutData = window.layoutData;

    if (!layoutData) {
        console.error('Layout data not available');
        window.showTooltip('Error loading layout data. Please try again.');
        return;
    }

    // Log detailed layout data for debugging
    console.group('Layout Data Details');
    console.log('Paper Size:', layoutData.paper_width, 'x', layoutData.paper_height);
    console.log('Sticker Size:', layoutData.sticker.width, 'x', layoutData.sticker.height);
    console.log('Total Sticker Positions:', layoutData.positions.length);
    console.log('Grid Layout:', `${layoutData.stickers_per_row} × ${layoutData.rows_per_page}`);
    console.groupEnd();

    const layoutId = document.getElementById('layout-id').value;
    const imageBase64 = document.getElementById('image-base64').value;












    // Initialize canvas with fabric.js
    const canvas = new fabric.Canvas('layout-canvas', {
        backgroundColor: 'white',
        preserveObjectStacking: true,
        centeredScaling: true
    });

    // Create a large paper background
    const paperBackground = new fabric.Rect({
        left: -1000,
        top: -1000,
        width: 10000,
        height: 10000,
        fill: 'white',
        selectable: false,
        evented: false,
        excludeFromExport: false
    });

    // Add to canvas and send to back
    canvas.add(paperBackground);
    paperBackground.sendToBack();

    // Store reference
    canvas.paperBackground = paperBackground;

    // Update background position and size during zoom and pan
    canvas.on('after:render', function () {
        // Only proceed if we have the background rectangle
        if (!canvas.paperBackground) return;

        // Get current viewport transform
        const vpt = canvas.viewportTransform;

        // Calculate the visible area in canvas coordinates
        const visibleLeft = -vpt[4] / vpt[0];
        const visibleTop = -vpt[5] / vpt[3];
        const visibleWidth = canvas.width / vpt[0];
        const visibleHeight = canvas.height / vpt[3];

        // Position the background to cover the visible area
        canvas.paperBackground.set({
            left: visibleLeft - 100,  // Extra margin
            top: visibleTop - 100,    // Extra margin
            width: visibleWidth + 200, // Extra width
            height: visibleHeight + 200 // Extra height
        });

        // Ensure it's at the bottom
        canvas.paperBackground.sendToBack();
    });





    // History for undo/redo
    const history = {
        canUndo: false,
        canRedo: false,
        states: [],
        currentStateIndex: -1,
        maxStates: 30
    };




    
    // Calculate the canvas size to fit the screen
    function calculateBestFit() {
        // Get container dimensions
        const container = document.querySelector('.canvas-container');
        const containerWidth = container ? container.clientWidth - 40 : window.innerWidth - 360; // Account for sidebar
        const containerHeight = window.innerHeight - 100; // Allow for UI elements

        // Paper dimensions in mm
        const paperWidth = layoutData.paper_width;
        const paperHeight = layoutData.paper_height;

        // Calculate scale factors to fit
        const widthRatio = containerWidth / paperWidth;
        const heightRatio = containerHeight / paperHeight;

        // Use smallest ratio to ensure it fits both dimensions
        const fitScaleFactor = Math.min(widthRatio, heightRatio);

        return {
            width: Math.round(paperWidth * fitScaleFactor),
            height: Math.round(paperHeight * fitScaleFactor),
            scaleFactor: fitScaleFactor
        };
    }



    


    // Get the best fit dimensions
    const bestFit = calculateBestFit();

    // Set canvas dimensions based on the calculated best fit
    canvas.setWidth(bestFit.width);
    canvas.setHeight(bestFit.height);

    // Scale factor is now dynamic based on screen size
    const scaleFactor = bestFit.scaleFactor;

    console.log('Dynamic scaling:', {
        canvasWidth: bestFit.width,
        canvasHeight: bestFit.height,
        scaleFactor: scaleFactor.toFixed(2) + ' pixels per mm'
    });












    


    // Keep track of zoom level
    let zoomLevel = 1;

























    // Get display settings controls
    const showGridCheckbox = document.getElementById('show-grid');
    const showMarginsCheckbox = document.getElementById('show-margins');
    const lockStickersCheckbox = document.getElementById('lock-stickers');
    const zoomLevelInput = document.getElementById('zoom-level');
    const zoomPercentage = document.getElementById('zoom-percentage');

    // Undo/Redo buttons
    const undoBtn = document.getElementById('undo-btn');
    const redoBtn = document.getElementById('redo-btn');
    const mobileUndoBtn = document.getElementById('mobile-undo-btn');
    const mobileRedoBtn = document.getElementById('mobile-redo-btn');

    // Create arrays to store sticker objects
    const stickers = [];

    // Draw margins
    const marginRect = new fabric.Rect({
        left: layoutData.margins.left * scaleFactor,
        top: layoutData.margins.top * scaleFactor,
        width: (layoutData.paper_width - layoutData.margins.left - layoutData.margins.right) * scaleFactor,
        height: (layoutData.paper_height - layoutData.margins.top - layoutData.margins.bottom) * scaleFactor,
        fill: 'transparent',
        stroke: '#0d6efd',
        strokeDashArray: [5, 5],
        strokeWidth: 1.5,
        selectable: false,
        hoverCursor: 'default',
        rx: 4,
        ry: 4
    });
    canvas.add(marginRect);

    // Draw grid lines
    const gridLines = [];



    // Add this function to your editor1.js file
    // Place it after sticker functions but before event handlers

    function rotateSelectedSticker(angle) {
        const activeObject = canvas.getActiveObject();
        if (activeObject && stickers.includes(activeObject)) {
            // Get current angle and add new angle
            const currentAngle = activeObject.angle || 0;
            const newAngle = (currentAngle + angle) % 360;

            // Apply rotation
            activeObject.rotate(newAngle);
            canvas.renderAll();

            // Update display if needed
            const rotationAngleElement = document.getElementById('rotation-angle');
            if (rotationAngleElement) {
                rotationAngleElement.textContent = Math.round(newAngle) + '°';
            }

            // Save state
            saveState();

            // Show tooltip
            window.showTooltip(`Rotated sticker to ${Math.round(newAngle)}°`);
        } else {
            window.showTooltip('Select a sticker to rotate');
        }
    }

    function createGridLines(currentScaleFactor = scaleFactor) {
        // Clear existing grid lines
        gridLines.forEach(line => canvas.remove(line));
        gridLines.length = 0;

        // Create horizontal grid lines
        for (let row = 0; row <= layoutData.rows_per_page; row++) {
            const y = (layoutData.margins.top + row * (layoutData.sticker.height + layoutData.spacing.vertical)) * currentScaleFactor;
            const line = new fabric.Line(
                [
                    layoutData.margins.left * currentScaleFactor,
                    y,
                    (layoutData.paper_width - layoutData.margins.right) * currentScaleFactor,
                    y
                ],
                {
                    stroke: '#ddd',
                    selectable: false,
                    hoverCursor: 'default'
                }
            );
            gridLines.push(line);
            canvas.add(line);
        }

        // Create vertical grid lines
        for (let col = 0; col <= layoutData.stickers_per_row; col++) {
            const x = (layoutData.margins.left + col * (layoutData.sticker.width + layoutData.spacing.horizontal)) * currentScaleFactor;
            const line = new fabric.Line(
                [
                    x,
                    layoutData.margins.top * currentScaleFactor,
                    x,
                    (layoutData.paper_height - layoutData.margins.bottom) * currentScaleFactor
                ],
                {
                    stroke: '#ddd',
                    selectable: false,
                    hoverCursor: 'default'
                }
            );
            gridLines.push(line);
            canvas.add(line);
        }

        // Send grid lines to back
        gridLines.forEach(line => line.sendToBack());
        marginRect.bringForward();
    }





    // Initialize grid
    createGridLines();


    // Handle window resize
    window.addEventListener('resize', function () {
        // Debounce resize
        if (this.resizeTimeout) clearTimeout(this.resizeTimeout);

        this.resizeTimeout = setTimeout(function () {
            const newBestFit = calculateBestFit();

            // Only update if dimensions changed significantly
            if (Math.abs(newBestFit.width - canvas.width) > 10 ||
                Math.abs(newBestFit.height - canvas.height) > 10) {

                // Save current viewport state
                const currentZoom = zoomLevel;
                const vpt = canvas.viewportTransform.slice();

                // Calculate the scale change ratio
                const scaleRatio = newBestFit.scaleFactor / scaleFactor;

                // Update canvas dimensions
                canvas.setWidth(newBestFit.width);
                canvas.setHeight(newBestFit.height);

                // Scale all stickers to maintain physical size
                canvas.getObjects().forEach(obj => {
                    if (obj !== marginRect && !gridLines.includes(obj)) {
                        obj.set({
                            left: obj.left * scaleRatio,
                            top: obj.top * scaleRatio,
                            scaleX: obj.scaleX * scaleRatio,
                            scaleY: obj.scaleY * scaleRatio
                        });
                    }
                });

                // Redraw grid and margins with new scale factor
                createGridLines(newBestFit.scaleFactor);

                // Update margin rectangle
                marginRect.set({
                    left: layoutData.margins.left * newBestFit.scaleFactor,
                    top: layoutData.margins.top * newBestFit.scaleFactor,
                    width: (layoutData.paper_width - layoutData.margins.left - layoutData.margins.right) * newBestFit.scaleFactor,
                    height: (layoutData.paper_height - layoutData.margins.top - layoutData.margins.bottom) * newBestFit.scaleFactor
                });

                // Reset viewport transform while maintaining zoom
                canvas.setViewportTransform([
                    vpt[0], 0, 0, vpt[3],
                    vpt[4] * scaleRatio, vpt[5] * scaleRatio
                ]);

                canvas.renderAll();
            }
        }, 250);
    });







    // Load sticker image
    const loadImage = function () {
        console.log('DEBUG: Starting image load process');
        window.showLoading('Loading your layout...');

        let imageBase64 = document.getElementById('image-base64').value;
        console.log('DEBUG: Image data length:', imageBase64.length);

        if (!imageBase64.startsWith('data:image')) {
            console.log('DEBUG: Fixing image data URL format');
            imageBase64 = 'data:image/png;base64,' + imageBase64;
        }

        const testImg = new Image();
        testImg.onload = function () {
            console.log('DEBUG: Test image loaded successfully:', testImg.width, 'x', testImg.height);

            fabric.Image.fromURL(imageBase64, function (img) {
                if (!img) {
                    console.error('ERROR: Failed to create Fabric image object');
                    window.hideLoading();
                    window.showTooltip('Error loading image. Please try again.');
                    return;
                }

                console.log('DEBUG: Fabric image created:', img.width, 'x', img.height);

                const stickerWidth = layoutData.sticker.width * scaleFactor;
                const stickerHeight = layoutData.sticker.height * scaleFactor;

                const scale = Math.min(
                    stickerWidth / img.width,
                    stickerHeight / img.height
                );

                img.scale(scale);
                console.log('DEBUG: Image scaled by factor:', scale);

                let stickersLoaded = 0;
                const totalStickers = layoutData.positions.length;
                console.log('DEBUG: About to create', totalStickers, 'stickers');

                layoutData.positions.forEach((position, index) => {
                    img.clone(function (sticker) {
                        if (!sticker) {
                            console.error('ERROR: Failed to clone sticker at position', index);
                            return;
                        }

                        sticker.set({
                            left: position.x * scaleFactor + (stickerWidth / 2),
                            top: position.y * scaleFactor + (stickerHeight / 2),
                            originX: 'center',
                            originY: 'center',
                            hasControls: true,
                            hasBorders: true,
                            borderColor: '#2196F3',
                            cornerColor: '#2196F3',
                            cornerSize: 8,
                            transparentCorners: false,
                            data: {
                                position: index,
                                originalX: position.x,
                                originalY: position.y
                            }
                        });

                        stickers.push(sticker);
                        canvas.add(sticker);
                        console.log('DEBUG: Added sticker', index, 'at position', position.x, position.y);

                        stickersLoaded++;
                        if (stickersLoaded === totalStickers) {
                            console.log('DEBUG: All stickers loaded successfully');
                            canvas.renderAll();
                            saveState();
                            window.hideLoading();
                            window.showTooltip('Layout loaded successfully! You can drag stickers to adjust positions.');
                        }
                    });
                });
            }, { crossOrigin: 'anonymous' });
        };

        testImg.onerror = function () {
            console.error('ERROR: Failed to load test image');
            window.hideLoading();
            window.showTooltip('Error loading image. Please check the image format.');
        };

        testImg.src = imageBase64;
    };

    // Call the loadImage function after canvas initialization
    loadImage();

    // Undo/Redo functions
    function saveState() {
        // Serialize the canvas
        const json = JSON.stringify(canvas.toJSON(['data']));

        // If we're not at the end of the history array, remove the future states
        if (history.currentStateIndex < history.states.length - 1) {
            history.states = history.states.slice(0, history.currentStateIndex + 1);
        }

        // Add the new state
        history.states.push(json);
        history.currentStateIndex = history.states.length - 1;

        // Limit history size
        if (history.states.length > history.maxStates) {
            history.states.shift();
            history.currentStateIndex--;
        }

        // Update undo/redo buttons
        updateUndoRedoButtons();
    }

    function undo() {
        if (history.currentStateIndex > 0) {
            history.currentStateIndex--;
            loadState(history.states[history.currentStateIndex]);
            updateUndoRedoButtons();
            window.showTooltip('Undo: Previous arrangement restored');
        }
    }

    function redo() {
        if (history.currentStateIndex < history.states.length - 1) {
            history.currentStateIndex++;
            loadState(history.states[history.currentStateIndex]);
            updateUndoRedoButtons();
            window.showTooltip('Redo: Change reapplied');
        }
    }

    function loadState(state) {
        canvas.loadFromJSON(state, function () {
            canvas.renderAll();

            // Recreate stickers array reference for the new objects
            stickers.length = 0;
            canvas.forEachObject(function (obj) {
                if (obj.data && obj.data.position !== undefined) {
                    stickers[obj.data.position] = obj;
                }
            });
        });
    }

    function updateUndoRedoButtons() {
        // Enable/disable undo button
        if (history.currentStateIndex > 0) {
            undoBtn.classList.remove('disabled');
            mobileUndoBtn.classList.remove('disabled');
            history.canUndo = true;
        } else {
            undoBtn.classList.add('disabled');
            mobileUndoBtn.classList.add('disabled');
            history.canUndo = false;
        }

        // Enable/disable redo button
        if (history.currentStateIndex < history.states.length - 1) {
            redoBtn.classList.remove('disabled');
            mobileRedoBtn.classList.remove('disabled');
            history.canRedo = true;
        } else {
            redoBtn.classList.add('disabled');
            mobileRedoBtn.classList.add('disabled');
            history.canRedo = false;
        }
    }

    // Add event listeners for undo/redo
    undoBtn.addEventListener('click', function () {
        if (history.canUndo) undo();
    });

    redoBtn.addEventListener('click', function () {
        if (history.canRedo) redo();
    });

    mobileUndoBtn.addEventListener('click', function () {
        if (history.canUndo) undo();
    });

    mobileRedoBtn.addEventListener('click', function () {
        if (history.canRedo) redo();
    });

    // Add keyboard shortcuts for undo/redo
    document.addEventListener('keydown', function (e) {
        // Only if not in an input field
        if (e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA') {
            // Undo: Ctrl/Cmd + Z
            if (e.key === 'z' && (e.ctrlKey || e.metaKey) && !e.shiftKey) {
                e.preventDefault();
                if (history.canUndo) undo();
            }

            // Redo: Ctrl/Cmd + Y or Ctrl/Cmd + Shift + Z
            if ((e.key === 'y' && (e.ctrlKey || e.metaKey)) ||
                (e.key === 'z' && (e.ctrlKey || e.metaKey) && e.shiftKey)) {
                e.preventDefault();
                if (history.canRedo) redo();
            }

            // Toggle grid: G
            if (e.key === 'g') {
                e.preventDefault();
                showGridCheckbox.checked = !showGridCheckbox.checked;
                showGridCheckbox.dispatchEvent(new Event('change'));
            }

            // Toggle margins: M
            if (e.key === 'm') {
                e.preventDefault();
                showMarginsCheckbox.checked = !showMarginsCheckbox.checked;
                showMarginsCheckbox.dispatchEvent(new Event('change'));
            }

            // Toggle lock: L
            if (e.key === 'l') {
                e.preventDefault();
                lockStickersCheckbox.checked = !lockStickersCheckbox.checked;
                lockStickersCheckbox.dispatchEvent(new Event('change'));
            }
        }
    });

    // Track changes to canvas objects
    canvas.on('object:modified', function (e) {
        if (e.target && stickers.includes(e.target)) {
            // Save state when a sticker is modified
            saveState();

            // Show tooltip
            const index = stickers.indexOf(e.target);
            window.showTooltip(`Sticker #${index + 1} position updated`);
        }
    });

    canvas.on('mouse:over', function (e) {
        if (e.target && stickers.includes(e.target)) {
            const index = stickers.indexOf(e.target);
            e.target.set('borderColor', '#4CAF50');
            e.target.set('cornerColor', '#4CAF50');
            canvas.renderAll();
        }
    });

    canvas.on('mouse:out', function (e) {
        if (e.target && stickers.includes(e.target)) {
            e.target.set('borderColor', '#2196F3');
            e.target.set('cornerColor', '#2196F3');
            canvas.renderAll();
        }
    });





    

    // Add these after your other canvas event listeners

    canvas.on('selection:created', updateRotationDisplay);
    canvas.on('selection:updated', updateRotationDisplay);

    function updateRotationDisplay(e) {
        const selected = e.selected ? e.selected[0] : null;
        const rotationAngleElement = document.getElementById('rotation-angle');

        if (selected && rotationAngleElement) {
            const angle = Math.round(selected.angle || 0);
            rotationAngleElement.textContent = angle + '°';
        }
    }







    // Toggle grid visibility
    showGridCheckbox.addEventListener('change', function () {
        gridLines.forEach(line => {
            line.set('visible', this.checked);
        });
        canvas.renderAll();

        // Show tooltip
        window.showTooltip(this.checked ? 'Grid visible' : 'Grid hidden');
    });

    // Toggle margins visibility
    showMarginsCheckbox.addEventListener('change', function () {
        marginRect.set('visible', this.checked);
        canvas.renderAll();

        // Show tooltip
        window.showTooltip(this.checked ? 'Margins visible' : 'Margins hidden');
    });

    // Toggle sticker lock
    lockStickersCheckbox.addEventListener('change', function () {
        stickers.forEach(sticker => {
            sticker.set('selectable', !this.checked);
            sticker.set('lockMovementX', this.checked);
            sticker.set('lockMovementY', this.checked);

            // Update controls appearance
            if (this.checked) {
                sticker.set('hasControls', false);
                sticker.set('hasBorders', false);
            } else {
                sticker.set('hasControls', true);
                sticker.set('hasBorders', true);
            }
        });
        canvas.renderAll();

        // Show tooltip
        window.showTooltip(this.checked ? 'Stickers locked' : 'Stickers unlocked');
    });









    // Reset layout to original grid positions
    document.getElementById('reset-layout-btn').addEventListener('click', function () {
        if (confirm('Are you sure you want to reset all stickers to their original grid positions?')) {
            // Show loading indicator
            window.showLoading('Resetting layout...');

            stickers.forEach((sticker, index) => {
                const position = layoutData.positions[index];
                const stickerWidth = layoutData.sticker.width * scaleFactor;
                const stickerHeight = layoutData.sticker.height * scaleFactor;

                sticker.set({
                    left: position.x * scaleFactor + (stickerWidth / 2),
                    top: position.y * scaleFactor + (stickerHeight / 2)
                });
            });

            canvas.renderAll();

            // Save state
            saveState();

            // Hide loading indicator
            setTimeout(() => {
                window.hideLoading();

                // Show tooltip
                window.showTooltip('Layout reset to original grid');
            }, 500);
        }
    });










    // Direct replacement for your existing zoom code - same structure




    // Zoom in button

    // Keep track of zoom level
    // let zoomLevel = 1;

    // Zoom in button
    document.getElementById('zoom-in-btn').addEventListener('click', function () {
        if (zoomLevel < 5) {
            zoomLevel += 0.1;
            updateZoom();
        }
    });

    // Zoom out button
    document.getElementById('zoom-out-btn').addEventListener('click', function () {
        if (zoomLevel > 0.3) {
            zoomLevel -= 0.1;
            updateZoom();
        }
    });

    // Zoom reset button
    document.getElementById('zoom-reset-btn').addEventListener('click', function () {
        zoomLevel = 1;
        updateZoom();

        // Center the view as well
        canvas.viewportTransform[4] = 0;
        canvas.viewportTransform[5] = 0;
        canvas.renderAll();
    });

    // Zoom slider
    zoomLevelInput.addEventListener('input', function () {
        zoomLevel = parseInt(this.value) / 100;
        updateZoom();
    });






    // 2. Fix for the zooming functionality (in editor.js)
    // Replace the updateZoom function with:

    // function updateZoom() {
    //     // Get current center point
    //     const vpt = canvas.viewportTransform;
    //     const center = {
    //         x: (canvas.width / 2 - vpt[4]) / vpt[0],
    //         y: (canvas.height / 2 - vpt[5]) / vpt[0]
    //     };

    //     // Apply zoom using viewport transform
    //     canvas.setZoom(zoomLevel);

    //     // Recenter after zoom
    //     canvas.viewportTransform[4] = canvas.width / 2 - center.x * zoomLevel;
    //     canvas.viewportTransform[5] = canvas.height / 2 - center.y * zoomLevel;

    //     // Force render
    //     canvas.renderAll();

    //     // Update displayed percentage
    //     zoomPercentage.textContent = Math.round(zoomLevel * 100) + '%';

    //     // Update zoom slider
    //     zoomLevelInput.value = Math.round(zoomLevel * 100);
    // }

    // // Also update the mouse wheel zoom handler to use setZoom:
    // canvas.on('mouse:wheel', function (opt) {
    //     const delta = opt.e.deltaY;
    //     let zoom = canvas.getZoom();

    //     // Calculate new zoom
    //     zoom = delta > 0 ? zoom * 0.9 : zoom * 1.1;

    //     // Limit zoom
    //     if (zoom > 5) zoom = 5;
    //     if (zoom < 0.3) zoom = 0.3;

    //     // Get mouse position
    //     const pointer = canvas.getPointer(opt.e);

    //     // Zoom to point under mouse
    //     canvas.zoomToPoint({ x: pointer.x, y: pointer.y }, zoom);

    //     // Update zoom level variable
    //     zoomLevel = zoom;

    //     // Update UI
    //     zoomPercentage.textContent = Math.round(zoomLevel * 100) + '%';
    //     zoomLevelInput.value = Math.round(zoomLevel * 100);

    //     // Prevent default scrolling
    //     opt.e.preventDefault();
    //     opt.e.stopPropagation();
    // });











    // Center canvas view (update existing function)
    document.getElementById('center-view-btn').addEventListener('click', function () {
        // Reset zoom
        zoomLevel = 1;

        // Reset viewport transform
        canvas.setViewportTransform([1, 0, 0, 1, 0, 0]);

        // Update UI
        zoomPercentage.textContent = '100%';
        zoomLevelInput.value = 100;

        // Show tooltip
        window.showTooltip('View centered');
    });












    // Enhanced updateZoom function with debugging
    function updateZoom() {
        console.group('Zoom Debugging');
        console.log('Current zoomLevel:', zoomLevel);

        // Log the canvas state before zoom
        console.log('Canvas before zoom:', {
            width: canvas.width,
            height: canvas.height,
            backgroundColor: canvas.backgroundColor,
            viewportTransform: [...canvas.viewportTransform]
        });

        // Get current center point
        const vpt = canvas.viewportTransform;
        const center = {
            x: (canvas.width / 2 - vpt[4]) / vpt[0],
            y: (canvas.height / 2 - vpt[5]) / vpt[0]
        };
        console.log('Center point:', center);

        // Try two approaches for zooming to see which works better

        // Approach 1: Use setZoom with explicit centering
        console.log('Applying zoom with setZoom()');
        canvas.setZoom(zoomLevel);

        // Manual centering after zoom
        canvas.viewportTransform[4] = canvas.width / 2 - center.x * zoomLevel;
        canvas.viewportTransform[5] = canvas.height / 2 - center.y * zoomLevel;

        // Force re-render
        canvas.renderAll();

        // Log the canvas state after zoom
        console.log('Canvas after zoom:', {
            width: canvas.width,
            height: canvas.height,
            backgroundScale: {
                x: canvas.getZoom(),
                y: canvas.getZoom()
            },
            viewportTransform: [...canvas.viewportTransform]
        });

        // Update displayed percentage
        zoomPercentage.textContent = Math.round(zoomLevel * 100) + '%';
        zoomLevelInput.value = Math.round(zoomLevel * 100);

        console.groupEnd();
    }

    // Enhanced mouse wheel zoom handler with debugging
    canvas.on('mouse:wheel', function (opt) {
        console.group('Mouse Wheel Zoom');

        const delta = opt.e.deltaY;
        console.log('Wheel delta:', delta);

        let zoom = canvas.getZoom();
        console.log('Current zoom before change:', zoom);

        // Calculate new zoom
        zoom = delta > 0 ? zoom * 0.9 : zoom * 1.1;
        console.log('New calculated zoom:', zoom);

        // Limit zoom
        if (zoom > 5) zoom = 5;
        if (zoom < 0.3) zoom = 0.3;
        console.log('Final zoom after limits applied:', zoom);

        // Get mouse position
        const pointer = canvas.getPointer(opt.e);
        console.log('Mouse position:', pointer);

        try {
            // Zoom to point under mouse
            console.log('Calling zoomToPoint()');
            canvas.zoomToPoint({ x: pointer.x, y: pointer.y }, zoom);

            // Log viewport transform after zoom
            console.log('Viewport transform after zoom:', [...canvas.viewportTransform]);

            // Update zoom level variable
            zoomLevel = zoom;

            // Update UI
            zoomPercentage.textContent = Math.round(zoomLevel * 100) + '%';
            zoomLevelInput.value = Math.round(zoomLevel * 100);
        } catch (error) {
            console.error('Error during zoomToPoint:', error);
        }

        // Prevent default scrolling
        opt.e.preventDefault();
        opt.e.stopPropagation();

        console.groupEnd();
    });

    // Add background debugging function
    function debugCanvasBackground() {
        console.group('Canvas Background Debug');

        // Check if background color is applied properly
        console.log('Canvas backgroundColor property:', canvas.backgroundColor);

        // Get the actual DOM elements to check their styles
        const lowerCanvas = document.querySelector('.lower-canvas');
        const upperCanvas = document.querySelector('.upper-canvas');
        const canvasContainer = document.querySelector('.canvas-container');

        if (lowerCanvas) {
            console.log('Lower canvas element:', lowerCanvas);
            console.log('Lower canvas computed style:', {
                backgroundColor: getComputedStyle(lowerCanvas).backgroundColor,
                width: getComputedStyle(lowerCanvas).width,
                height: getComputedStyle(lowerCanvas).height,
                transform: getComputedStyle(lowerCanvas).transform
            });
        } else {
            console.warn('Lower canvas element not found');
        }

        if (upperCanvas) {
            console.log('Upper canvas element:', upperCanvas);
            console.log('Upper canvas computed style:', {
                backgroundColor: getComputedStyle(upperCanvas).backgroundColor,
                width: getComputedStyle(upperCanvas).width,
                height: getComputedStyle(upperCanvas).height,
                transform: getComputedStyle(upperCanvas).transform
            });
        } else {
            console.warn('Upper canvas element not found');
        }

        if (canvasContainer) {
            console.log('Canvas container element:', canvasContainer);
            console.log('Canvas container computed style:', {
                backgroundColor: getComputedStyle(canvasContainer).backgroundColor,
                width: getComputedStyle(canvasContainer).width,
                height: getComputedStyle(canvasContainer).height,
                overflow: getComputedStyle(canvasContainer).overflow
            });
        } else {
            console.warn('Canvas container element not found');
        }

        console.groupEnd();
    }

    // Call background debug on load and after zoom
    document.addEventListener('DOMContentLoaded', function () {
        // Wait for canvas to be fully initialized
        setTimeout(debugCanvasBackground, 1000);

        // Add a button to debug the canvas background
        const debugBtn = document.createElement('button');
        debugBtn.textContent = 'Debug Canvas';
        debugBtn.style.position = 'fixed';
        debugBtn.style.bottom = '10px';
        debugBtn.style.right = '10px';
        debugBtn.style.zIndex = '9999';
        debugBtn.style.padding = '5px 10px';
        debugBtn.style.backgroundColor = '#f44336';
        debugBtn.style.color = 'white';
        debugBtn.style.border = 'none';
        debugBtn.style.borderRadius = '4px';
        debugBtn.style.cursor = 'pointer';

        debugBtn.addEventListener('click', function () {
            debugCanvasBackground();
            window.showTooltip('Check console for canvas debug info');
        });

        document.body.appendChild(debugBtn);
    });

    // Alternative approach: try adding explicit background object
    function addExplicitBackground() {
        // Create a background rectangle that covers the entire canvas
        const backgroundRect = new fabric.Rect({
            width: canvas.width,
            height: canvas.height,
            fill: 'white',
            selectable: false,
            evented: false,
            excludeFromExport: true,
            id: 'background-rect'
        });

        // Add to canvas and send to back
        canvas.add(backgroundRect);
        backgroundRect.sendToBack();

        // Store reference to background
        canvas.backgroundRect = backgroundRect;

        console.log('Added explicit background rectangle:', backgroundRect);

        // Update background when canvas dimensions change
        canvas.on('resize', function () {
            if (canvas.backgroundRect) {
                canvas.backgroundRect.set({
                    width: canvas.width,
                    height: canvas.height
                });
                canvas.renderAll();
                console.log('Updated background rectangle after resize');
            }
        });
    }

    // Call this function if you want to try the explicit background approach
    // addExplicitBackground();




















    // Save layout
    document.getElementById('save-layout-btn').addEventListener('click', function () {
        // Get layout name
        const layoutName = document.getElementById('layout-name').value;

        // Get positions of all stickers
        const positions = [];
        stickers.forEach((sticker, index) => {
            const centerX = sticker.left;
            const centerY = sticker.top;
            const width = sticker.width * sticker.scaleX;
            const height = sticker.height * sticker.scaleY;

            // Calculate top-left corner position
            const x = (centerX - (width / 2)) / scaleFactor;
            const y = (centerY - (height / 2)) / scaleFactor;

            positions.push({
                x: x,
                y: y,
                row: Math.floor((y - layoutData.margins.top) / (layoutData.sticker.height + layoutData.spacing.vertical)),
                col: Math.floor((x - layoutData.margins.left) / (layoutData.sticker.width + layoutData.spacing.horizontal)),
                index: sticker.data.position
            });
        });

        // Show loading indicator
        window.showLoading('Saving layout...');

        // Send data to server
        fetch(`/save-layout/${layoutId}/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({
                name: layoutName,
                positions: positions
            })
        })
            .then(response => response.json())
            .then(data => {
                window.hideLoading();

                if (data.success) {
                    // Show success modal
                    const saveSuccessModal = new bootstrap.Modal(document.getElementById('saveSuccessModal'));
                    saveSuccessModal.show();

                    // Show tooltip
                    window.showTooltip('Layout saved successfully!');
                } else {
                    alert('Error saving layout: ' + data.error);
                }
            })
            .catch(error => {
                window.hideLoading();
                console.error('Error:', error);
                alert('Error saving layout. Please try again.');
            });
    });

    // Download PNG
    document.getElementById('download-png-btn').addEventListener('click', function () {
        // Show loading indicator
        window.showLoading('Generating PNG...');

        // Prepare canvas for download by hiding grid and margins if needed
        const gridVisible = showGridCheckbox.checked;
        const marginsVisible = showMarginsCheckbox.checked;

        // Temporarily hide elements
        if (gridVisible) {
            gridLines.forEach(line => line.set('visible', false));
        }

        if (marginsVisible) {
            marginRect.set('visible', false);
        }

        // Update canvas after hiding elements
        canvas.renderAll();

        // Create the download
        const dataURL = canvas.toDataURL({
            format: 'png',
            quality: 1.0,
            multiplier: 2 // Higher resolution
        });

        // Create download link
        const link = document.createElement('a');
        const layoutName = document.getElementById('layout-name').value.replace(/\s+/g, '_').toLowerCase();
        link.download = `${layoutName || 'sticker_layout'}.png`;
        link.href = dataURL;
        document.body.appendChild(link);

        // Delay click to give canvas time to render
        setTimeout(() => {
            link.click();
            document.body.removeChild(link);

            // Restore visibility
            if (gridVisible) {
                gridLines.forEach(line => line.set('visible', true));
            }

            if (marginsVisible) {
                marginRect.set('visible', true);
            }

            // Update canvas after restoring elements
            canvas.renderAll();

            // Hide loading indicator
            window.hideLoading();

            // Show tooltip
            window.showTooltip('PNG download complete');
        }, 500);
    });

    // Clone selected sticker
    document.getElementById('clone-sticker-btn').addEventListener('click', function () {
        const activeObject = canvas.getActiveObject();
        if (activeObject && stickers.includes(activeObject)) {
            activeObject.clone(function (cloned) {
                // Offset the clone slightly
                cloned.set({
                    left: cloned.left + 20,
                    top: cloned.top + 20,
                    data: {
                        position: stickers.length,
                        originalX: activeObject.data.originalX,
                        originalY: activeObject.data.originalY
                    }
                });

                // Add to canvas and stickers array
                stickers.push(cloned);
                canvas.add(cloned);
                canvas.setActiveObject(cloned);
                canvas.renderAll();

                // Save state
                saveState();

                // Show tooltip
                window.showTooltip('Sticker cloned');

                // Update layout stats
                updateLayoutStats();
            });
        } else {
            window.showTooltip('Select a sticker to clone');
        }
    });





    // Delete selected sticker
    document.getElementById('delete-sticker-btn').addEventListener('click', function () {
        const activeObject = canvas.getActiveObject();
        if (activeObject && stickers.includes(activeObject)) {
            // Remove from canvas and stickers array
            canvas.remove(activeObject);
            const index = stickers.indexOf(activeObject);
            stickers.splice(index, 1);

            // Save state
            saveState();

            // Show tooltip
            window.showTooltip('Sticker deleted');

            // Update layout stats
            updateLayoutStats();
        } else {
            window.showTooltip('Select a sticker to delete');
        }
    });








    
    // Add new sticker
    document.getElementById('add-sticker-btn').addEventListener('click', function () {
        // Use the same image as existing stickers
        const existingSticker = stickers[0];
        if (existingSticker) {
            existingSticker.clone(function (cloned) {
                // Place in the center of the canvas viewport
                const vpt = canvas.viewportTransform;
                const centerX = (canvas.width / 2 - vpt[4]) / vpt[0];
                const centerY = (canvas.height / 2 - vpt[5]) / vpt[0];

                cloned.set({
                    left: centerX,
                    top: centerY,
                    data: {
                        position: stickers.length,
                        originalX: layoutData.margins.left,
                        originalY: layoutData.margins.top
                    }
                });

                // Add to canvas and stickers array
                stickers.push(cloned);
                canvas.add(cloned);
                canvas.setActiveObject(cloned);
                canvas.renderAll();

                // Save state
                saveState();

                // Show tooltip
                window.showTooltip('New sticker added');

                // Update layout stats
                updateLayoutStats();
            });
        }
    });

    // Update layout statistics
    function updateLayoutStats() {
        const statsElement = document.getElementById('layout-stats');
        if (statsElement) {
            statsElement.textContent = `${stickers.length} stickers on page`;
        }
    }

    // Helper function to get CSRF token
    function getCsrfToken() {
        const cookieValue = document.cookie
            .split('; ')
            .find(row => row.startsWith('csrftoken='))
            ?.split('=')[1];

        return cookieValue || '';
    }

    // Connect mobile controls to main functions
    document.getElementById('mobile-zoom-in').addEventListener('click', function () {
        document.getElementById('zoom-in-btn').click();
    });

    document.getElementById('mobile-zoom-out').addEventListener('click', function () {
        document.getElementById('zoom-out-btn').click();
    });

    document.getElementById('mobile-zoom-reset').addEventListener('click', function () {
        document.getElementById('zoom-reset-btn').click();
    });

    document.getElementById('mobile-add-btn').addEventListener('click', function () {
        document.getElementById('add-sticker-btn').click();
    });

    document.getElementById('mobile-clone-btn').addEventListener('click', function () {
        document.getElementById('clone-sticker-btn').click();
    });

    document.getElementById('mobile-delete-btn').addEventListener('click', function () {
        document.getElementById('delete-sticker-btn').click();
        
    });



    // Add these event listeners near your other button event listeners

    document.getElementById('rotate-left-btn').addEventListener('click', function () {
        rotateSelectedSticker(-30); // Rotate 15 degrees counter-clockwise
    });

    document.getElementById('rotate-right-btn').addEventListener('click', function () {
        rotateSelectedSticker(30); // Rotate 15 degrees clockwise
    });

    document.getElementById('reset-rotation-btn').addEventListener('click', function () {
        const activeObject = canvas.getActiveObject();
        if (activeObject && stickers.includes(activeObject)) {
            activeObject.rotate(0);
            canvas.renderAll();

            const rotationAngleElement = document.getElementById('rotation-angle');
            if (rotationAngleElement) {
                rotationAngleElement.textContent = '0°';
            }

            saveState();
            window.showTooltip('Reset rotation to 0°');
        } else {
            window.showTooltip('Select a sticker to reset rotation');
        }
    });

    // Add a "Fit to Screen" button event handler if it exists
    const fitToScreenBtn = document.getElementById('fit-to-screen-btn');
    if (fitToScreenBtn) {
        fitToScreenBtn.addEventListener('click', function () {
            // Recalculate best fit
            const newBestFit = calculateBestFit();

            // Reset zoom
            zoomLevel = 1;
            updateZoom();

            // Reset pan
            canvas.viewportTransform[4] = 0;
            canvas.viewportTransform[5] = 0;
            canvas.renderAll();

            window.showTooltip('Layout fitted to screen');
        });
    }

    // Initialize undo/redo buttons
    updateUndoRedoButtons();

    // Show welcome tooltip
    setTimeout(() => {
        window.showTooltip('Welcome to the Sticker Layout Editor!', 3000);
    }, 1000);
});




