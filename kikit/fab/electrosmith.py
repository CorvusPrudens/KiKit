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

def adjustByReference(position, reference_position):
    if reference_position:
        return (position[0] - reference_position[0], position[1] - reference_position[1])
    else:
        return position

def getFrame(board_bb, top_ref_pos, bot_ref_pos):
    # Get frames
    frame_tl = adjustByReference((board_bb.GetX(), board_bb.GetY()), top_ref_pos)
    frame_br = adjustByReference(
        (board_bb.GetX() + board_bb.GetWidth(), board_bb.GetY() + board_bb.GetHeight()),
        top_ref_pos)

    # Reverse side
    frame_rev_tl = adjustByReference((board_bb.GetX() + board_bb.GetWidth(), board_bb.GetY()), bot_ref_pos)
    frame_rev_br = adjustByReference(
        (board_bb.GetX(), board_bb.GetY() + board_bb.GetHeight()),
        bot_ref_pos)

    return (frame_tl, frame_br, frame_rev_tl, frame_rev_br)

def fidToCentroid(fid, id):
    side = 'T' if not fid.IsFlipped() else 'B'
    identifier = "FD{}{}".format(side, id)
    return (identifier, toMm(fid.GetX()), toMm(fid.GetY()), side, 0.0, "Fiducial")

def getFootprintFromRef(ref, board, is_top=True):
    try:
        footprint = list(filter(lambda fp: fp.GetReference() == ref, board.GetFootprints()))[0]
        if is_top and footprint.GetLayer() != 0:
            raise ValueError(f"Component {ref} is not on the top side")
        elif not is_top and footprint.GetLayer() == 0:
            raise ValueError(f"Component {ref} is not on the bottom side")
        return footprint
    except IndexError:
        raise NameError(f"No component found with reference {ref}")

def generateRefPoints(image_tl, image_br, image_rev_tl, image_rev_br,
        board_tl, board_br, board_rev_tl, board_rev_br,
        top_ref, bot_ref, board_width, board_height,
        panel_width, panel_height, rows, cols):

    if top_ref:
        top_side = f"""Top Side SMD Job Creation Information
------------------------
Reference Component Designator
{top_ref}
------------------------

Panel Frame
------------------------
Top Left Offset (x, y) in mm:
{toMm(board_tl[0])}
{toMm(board_tl[1])}
------------------------
Bottom Right Offset (x, y) in mm:
{toMm(board_br[0])}
{toMm(board_br[1])}
------------------------

Image Frame
------------------------
Top Left Offset (x, y) in mm:
{toMm(image_tl[0])}
{toMm(image_tl[1])}
------------------------
Bottom Right Offset (x, y) in mm:
{toMm(image_br[0])}
{toMm(image_br[1])}
"""
    else:
        top_side = ""

    if bot_ref:
        bot_side = f"""Bottom Side SMD Job Creation Information
------------------------
Reference Component Designator
{bot_ref}
------------------------

Panel Frame
------------------------
Top Left Offset (x, y) in mm:
{toMm(board_rev_tl[0])}
{toMm(board_rev_tl[1])}
------------------------
Bottom Right Offset (x, y) in mm:
{toMm(board_rev_br[0])}
{toMm(board_rev_br[1])}
------------------------

Image Frame
------------------------
Top Left Offset (x, y) in mm:
{toMm(image_rev_tl[0])}
{toMm(image_rev_tl[1])}
------------------------
Bottom Right Offset (x, y) in mm:
{toMm(image_rev_br[0])}
{toMm(image_rev_br[1])}
"""
    else:
        bot_side = ""

    return f"""
{top_side}
{bot_side}

Panel Info:
------------------------
Number of Units (rows , columns):
{rows}
{cols}
------------------------
X Offset (mm):
{toMm(board_width) + 2}
------------------------
Y Offset (mm):
{toMm(board_height)}
------------------------
Total Panel Dimension (width, height) in mm:
{toMm(panel_width)}
{toMm(panel_height)}
"""

from kikit.panelize_ui import doPanelization
from kikit import panelize_ui_impl as ki
from kikit.common import findBoardBoundingBox, toMm

def exportElectrosmith(board, outputdir, schematic, rows, cols, top_ref, bot_ref, nametemplate, drc):
    """
    Prepare fabrication files for Electrosmith
    """

    # Input validation
    ensureValidBoard(board)
    ensureValidSch(schematic)

    loadedBoard = pcbnew.LoadBoard(board)

    project_name = os.path.basename(board).replace('.kicad_pcb', '')

    if drc:
        ensurePassingDrc(loadedBoard)

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
        fiducials={
            "type": "3fid",
            "hoffset": "10mm",
            "voffset": "3mm",
            "coppersize": "1mm",
            "opening": "2mm",
        },
        text={
            "type": "simple",
            "text": project_name,
            "width": "3mm",
            "height": "3mm",
            "thickness": "0.2mm",
            "voffset": "6mm"
        }
    )

    Path(outputdir).mkdir(parents=True, exist_ok=True)
    panelized_path = os.path.join(outputdir, f"{project_name}_{cols}X{rows}.kicad_pcb")
    doPanelization(board, panelized_path, preset)

    # Examine panelization for fiducials
    panelized_board: pcbnew.BOARD = pcbnew.LoadBoard(panelized_path)
    panel_components: list[pcbnew.FOOTPRINT] = panelized_board.GetFootprints()
    rail_fiducials = filter(lambda c: c.GetValue() == 'Fiducial', panel_components)

    # Ensure the fiducials only come from the rails
    original_components: list[pcbnew.FOOTPRINT] = loadedBoard.GetFootprints()
    # board_fiducials = filter(lambda c: c.GetValue() == 'Fiducial', original_components)
    rail_fiducials = filter(
        lambda c: c.GetReference() == "REF**",
        rail_fiducials
    )

    # Reference point positions
    top_ref_pos = getFootprintFromRef(top_ref, panelized_board).GetPosition() if top_ref else None
    bot_ref_pos = getFootprintFromRef(bot_ref, panelized_board, is_top=False).GetPosition() if bot_ref else None

    # Get frames
    image_tl, image_br, image_rev_tl, image_rev_br = getFrame(board_bb, top_ref_pos, bot_ref_pos)
    panel_bb = findBoardBoundingBox(panelized_board)
    panel_tl, panel_br, panel_rev_tl, panel_rev_br = getFrame(panel_bb, top_ref_pos, bot_ref_pos)

    ref_points = generateRefPoints(image_tl, image_br, image_rev_tl, image_rev_br,
        panel_tl, panel_br, panel_rev_tl, panel_rev_br, top_ref, bot_ref, board_bb.GetWidth(),
        board_bb.GetHeight(), panel_bb.GetWidth(), panel_bb.GetHeight(), rows, cols)

    gerberdir = os.path.join(outputdir, project_name)
    shutil.rmtree(gerberdir, ignore_errors=True)
    gerberImpl(board, gerberdir)

    archiveName = expandNameTemplate(nametemplate, project_name, loadedBoard)
    shutil.make_archive(os.path.join(outputdir, archiveName), "zip", outputdir, project_name)

    # Schematic materials
    components = extractComponents(schematic)
    bom, values = collectBom(components)
    panelized_board.GetDesignSettings().SetAuxOrigin(pcbnew.wxPoint(0, 0))
    posData = collectPosData(panelized_board, [], bom=components, posFilter=lambda _fp: True)
    # Append IPN data
    posData = list(map(lambda tup: (*tup, values[tup[0]]), posData))
    # Add fiducials
    for i, fiducial in enumerate(filter(lambda f: not f.IsFlipped(), rail_fiducials)):
        posData.append(fidToCentroid(fiducial, i + 1))
    for i, fiducial in enumerate(filter(lambda f: f.IsFlipped(), rail_fiducials)):
        posData.append(fidToCentroid(fiducial, i + 1))

    posDataToFile(posData, os.path.join(outputdir, expandNameTemplate(nametemplate, f'{project_name}-centroid', loadedBoard) + ".txt"))
    bomToCsv(bom, os.path.join(outputdir, expandNameTemplate(nametemplate, f'{project_name}-bom', loadedBoard) + ".csv"))
    with open(os.path.join(outputdir, "reference_points.txt"), 'w') as file:
        file.write(ref_points)
