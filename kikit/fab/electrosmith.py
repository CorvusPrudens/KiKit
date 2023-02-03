import click
from pcbnewTransition import pcbnew
import csv
import os
import sys
import shutil
from pathlib import Path
from kikit.fab.common import *
from kikit.common import *
from kikit.export import gerberImpl

def collectBom(components):
    bom = {}
    values = {}
    for c in components:
        if getUnit(c) != 1:
            continue
        reference = getReference(c)
        if hasattr(c, "in_bom") and not c.in_bom:
            continue
        if reference.startswith("#PWR") or reference.startswith("#FL"):
            continue
        c_type = (
            getField(c, "Value"),
            getField(c, "Footprint"),
        )
        bom[c_type] = bom.get(c_type, []) + [reference]
        values[reference] = c_type[0]
    return bom, values

def bomToCsv(bomData, filename):
    with open(filename, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["IPN", "Id", "Footprint"])
        for c_type, references in bomData.items():
            ipn, footprint = c_type
            writer.writerow([ipn, ' '.join(references), footprint])

from kikit.panelize_ui import doPanelization
from kikit import panelize_ui_impl as ki
from kikit.common import findBoardBoundingBox, toMm

def exportElectrosmith(board, outputdir, schematic, rows, cols, nametemplate, drc):
    """
    Prepare fabrication files for Electrosmith
    """

    # Input validation
    ensureValidBoard(board)
    ensureValidSch(schematic)

    loadedBoard = pcbnew.LoadBoard(board)

    board_bb = findBoardBoundingBox(loadedBoard)
    width = board_bb.GetWidth()

    # This leaves 5mm on either side
    rail_tab_width = f'{toMm(width) - 10}mm'

    # Do board panelization
    preset = ki.obtainPreset(
        [],
        layout={
            "type": "grid",
            "rows": rows,
            "cols": cols,
            "hspace": "2mm",
            "vspace": "0mm",
            "rotation": "0deg",
            "alternation": "none",
            "renamenet": "Board_{n}-{orig}",
            "renameref": "{orig}",
            "hbackbone": "0mm",
            "vbackbone": "0mm",
            "hboneskip": 0,
            "vboneskip": 0,
            "vbonecut": True,
            "hbonecut": True,
            "baketext": True,
            "code": "none",
            "arg": ""
        },
        framing={"type": "railstb", "width": "12.7mm"},
        tooling={
            "type": "4hole",
            "hoffset": "6mm",
            "voffset": "6mm",
            "size": "3mm"
        },
        cuts={
            "type": "vcuts",
            "clearance": "1mm",
            "layer": "Cmts_User",
        },
        tabs={
            "type": "fixed",
            "hcount": 0,
            "vcount": 1,
            "hwidth": "3mm",
            "vwidth": rail_tab_width,
            "mindistance": "10mm",
            "spacing": "10mm",
            "cutout": "1mm"
        },
    )
    doPanelization(board, os.path.join(outputdir, "panel.kicad_pcb"), preset)

    if drc:
        ensurePassingDrc(loadedBoard)

    Path(outputdir).mkdir(parents=True, exist_ok=True)

    gerberdir = os.path.join(outputdir, "gerber")
    shutil.rmtree(gerberdir, ignore_errors=True)
    gerberImpl(board, gerberdir)

    archiveName = expandNameTemplate(nametemplate, "gerbers", loadedBoard)
    shutil.make_archive(os.path.join(outputdir, archiveName), "zip", outputdir, "gerber")

    # Schematic materials
    components = extractComponents(schematic)
    bom, values = collectBom(components)
    posData = collectPosData(loadedBoard, [], bom=components, posFilter=lambda _fp: True)
    # Append IPN data
    posData = map(lambda tup: (*tup, values[tup[0]]), posData)

    posDataToFile(posData, os.path.join(outputdir, expandNameTemplate(nametemplate, "centroid", loadedBoard) + ".txt"))
    bomToCsv(bom, os.path.join(outputdir, expandNameTemplate(nametemplate, "bom", loadedBoard) + ".csv"))
