import sys
import numpy as np
import os
from collections import OrderedDict, defaultdict
from const import CMPID, R1, R2, R3, Z1, Z2


class AVComp(object):
    """ Represents a vulnerable area component. """
    def __init__(self, **args):
        self.x = args['x']
        self.y = args['y']
        self.z = args['z']
        self.name = args['name']


class AV(object):
    """ AV file parser. """
    def __init__(self, model=None):
        # The next five lines allow you to either pass in an external DataModel, in which case the AV object will
        # assign to that model's variables, or if no model is specified, it will assign to its own variables instead.
        if model is None:
            self.model = self
        else:
            self.model = model
        model = self.model
        self.avf = None
        model.comps = {}
        model.frag_ids = set()
        model.x_avg_loc, model.y_avg_loc = 0.0, 0.0
        model.x_loc, model.y_loc, model.z_loc = 0.0, 0.0, 0.0
        model.num_tables = None
        model.num_az, model.num_el, model.num_vl, model.num_ms = 0, 0, 0, 0
        model.azs = []
        model.els = []
        model.vls = []
        model.mss = []
        model.table_names = None
        self.vel_cutoff = None
        model.avs = None
        model.pes = None

    def _read_array(self):
        """
        Reads a line from an open AV file in the following format:
        num_items item_1 item_2 ... item_n
        If num_items doesn't match the number of items on the line, a ValueError is raised.

        :return: num_items, items
        """
        line = self.avf.readline().strip()
        try:
            n, rest = line.split(None, 1)
        except ValueError:
            n = 0
            rest = ''
        num_items = int(n)
        if num_items <= 0:
            raise ValueError('number of items in array is 0 or less!')
        items = [float(r) for r in rest.split()]
        return num_items, items

    def _read_av_header(self):
        """
        Reads an open AV file from the top, down to where the AV tables begin (after the mass array line.)
        :return: None
        """
        model = self.model
        self.avf.readline()  # skip past first header line
        self.avf.readline()  # skip past second header line
        tokens = self.avf.readline().strip().split()
        num_comps, metric = int(tokens[0]), int(tokens[1])
        self.avf.readline()  # skip past tire array
        self.avf.readline()  # skip past leak array
        self.avf.readline()  # skip past fire array
        tokens = self.avf.readline().strip().split()
        model.x_loc, model.y_loc, model.z_loc = float(tokens[0]), float(tokens[1]), float(tokens[2])
        for i in range(num_comps):
            tokens = self.avf.readline().strip().split(None, 4)
            comp = AVComp(x=float(tokens[1]), y=float(tokens[2]), z=float(tokens[3]), name=tokens[4])
            comp_id = int(tokens[0])
            model.comps[i+1] = comp
            if comp_id == 0:
                continue  # dummy component
            model.frag_ids.add(comp_id)
            model.x_avg_loc += comp.x
            model.y_avg_loc += comp.y
        self.avf.readline()  # AV HEADER LINES
        tokens = self.avf.readline().strip().split()
        model.num_tables, model.av_averaging = int(tokens[0]), int(tokens[1])
        model.x_avg_loc /= model.num_tables
        model.y_avg_loc /= model.num_tables
        model.num_az, model.azs = self._read_array()
        model.num_el, model.els = self._read_array()
        model.num_vl, model.vls = self._read_array()
        model.num_ms, model.mss = self._read_array()
        model.table_names = [[['' for _ in model.els] for _ in model.azs] for _ in range(model.num_tables)]
        self.vel_cutoff = [[[[None for _ in model.mss] for _ in model.els] for _ in model.azs]
                           for _ in range(model.num_tables)]
        model.avs = [[[[[0.0 for _ in model.vls] for _ in model.mss] for _ in model.els] for _ in model.azs]
                     for _ in range(model.num_tables)]
        model.pes = [[[[[0.0 for _ in model.vls] for _ in model.mss] for _ in model.els] for _ in model.azs]
                     for _ in range(model.num_tables)]

    def _read_av_tables(self, header_flag=True):
        """:header_flag: controls whitespace parsing of table name. See comments below.
        :return None"""
        model = self.model
        for icmp in range(model.num_tables):
            for iel in range(model.num_el):
                # -90 and 90 are handled differently since they have only one azimuth.
                polar_el = (float(model.els[iel]) == 90.0 or float(model.els[iel]) == -90.0)
                for iaz in range(model.num_az):
                    line = self.avf.readline().strip()
                    if model.av_averaging == 1:  # by azimuth
                        # each AV table header line is composed of "az el table_name", but table names can consist of
                        # sentences with whitespace in between words. When header_flag is True, the entire rest of
                        # the line is parsed as a single sentence. When False, only the first word is parsed.
                        if header_flag:
                            tokens = line.split(None, 2)  #
                        else:
                            tokens = line.split()
                        az, el = tokens[0], tokens[1]
                        model.table_names[icmp][iaz][iel] = tokens[2]
                    else:
                        # each AV table header line is composed of "az el table_name", but table names can consist of
                        # sentences with whitespace in between words. When header_flag is True, the entire rest of
                        # the line is parsed as a single sentence. When False, only the first word is parsed.
                        if header_flag:
                            tokens = line.split(None, 1)
                        else:
                            tokens = line.split()
                        el = tokens[0]
                        az = model.azs[0]
                        model.table_names[icmp][iaz][iel] = tokens[1]
                    if float(az) != float(model.azs[iaz]):
                        raise ValueError("Azimuth value didn't match appropriate azimuth array value: component {0}, "
                                         "azimuth {1}.".format(icmp+1, iaz+1))
                    if float(el) != float(model.els[iel]):
                        raise ValueError("Elevation value didn't match appropriate elevation array value: component "
                                         "{0}, azimuth {1}, elevation {2}.".format(icmp+1, iaz+1, iel+1))
                    for ims in range(model.num_ms):
                        tokens = self.avf.readline().strip().split()
                        ms = tokens[0]
                        if float(ms) != float(model.mss[ims]):
                            raise ValueError("Mass value didn't match appropriate mass array value: component {0}, "
                                             "azimuth {1}, elevation {2}, mass {3}.".format(icmp+1, iaz+1, iel+1,
                                                                                            ims+1))
                        for ivl in range(model.num_vl):
                            av = float(tokens[ivl+2])
                            model.avs[icmp][iaz][iel][ims][ivl] = av
                            if av < 0.0:
                                raise ValueError("Bad fragment AV: component {0}, azimuth {1}, elevation {2}, "
                                                 "mass {3}, velocity {4}.".format(icmp+1, iaz+1, iel+1, ims+1, ivl+1))
                        if model.num_vl + 2 < len(tokens):  # detect velocity cutoff at end of line
                            self.vel_cutoff[icmp][iaz][iel][ims] = tokens[model.num_vl + 2]
                        if model.av_averaging < 1:  # azimuth averaged (either type)
                            tokens = self.avf.readline().strip().split()
                            for ivl in range(model.num_vl):
                                pe = float(tokens[ivl+1])
                                model.pes[icmp][iaz][iel][ims][ivl] = pe
                                if pe < 0.0 or pe > 1.0:
                                    raise ValueError("Bad fragment PE: component {0}, azimuth {1}, elevation {2}, "
                                                     "mass {3}, velocity {4}.".format(icmp+1, iaz+1, iel+1, ims+1,
                                                                                      ivl+1))
                        else:
                            for ivl in range(model.num_vl):
                                model.pes[icmp][iaz][iel][ims][ivl] = 1.0
                    if model.av_averaging == 1 and polar_el:
                        break  # read only a single az/el pair if we're at a 90 degree elevation

    def read(self, av_file):
        with open(av_file) as self.avf:
            self._read_av_header()
            self._read_av_tables(True)


class Surfaces(object):
    """ Surface file parser. """
    def __init__(self, model=None):
        # The next five lines allow you to either pass in an external DataModel, in which case the AV object will
        # assign to that model's variables, or if no model is specified, it will assign to its own variables instead.
        if model is None:
            self.model = self
        else:
            self.model = model
        model = self.model
        self.srf = None
        model.surf_names = []
        model.surfaces = []
        model.srf_min_x, model.srf_max_x = sys.maxsize, -sys.maxsize
        model.srf_min_y, model.srf_max_y = sys.maxsize, -sys.maxsize
        model.srf_max_z = -sys.maxsize

    def read(self, srf_file):
        """
        Reads surface file data

        Parameters
        ----------
        srf_file : Target surface filename

        Returns None
        -------
        """
        model = self.model
        with open(srf_file) as self.srf:
            self.srf.readline().strip()
            tokens = self.srf.readline().strip().split()
            num_surfaces, metric = int(tokens[0]), float(tokens[1])
            for i in range(num_surfaces):
                tokens = self.srf.readline().strip().split(None, 14)
                x1, y1, z1 = float(tokens[0]), float(tokens[1]), float(tokens[2])
                x2, y2, z2 = float(tokens[3]), float(tokens[4]), float(tokens[5])
                x3, y3, z3 = float(tokens[6]), float(tokens[7]), float(tokens[8])
                x4, y4, z4 = float(tokens[9]), float(tokens[10]), float(tokens[11])
                model.surf_names.append(tokens[14])
                model.surfaces.extend([[x1, y1, z1], [x2, y2, z2], [x3, y3, z3], [x4, y4, z4]])
                model.srf_min_x = min(model.srf_min_x, x1, x2, x3, x4)
                model.srf_max_x = max(model.srf_max_x, x1, x2, x3, x4)
                model.srf_min_y = min(model.srf_min_y, y1, y2, y3, y4)
                model.srf_max_y = max(model.srf_max_y, y1, y2, y3, y4)
                model.srf_max_z = max(model.srf_max_z, z1, z2, z3, z4)


class Output(object):
    """ The JMAE .out file holds filepaths to the other auxiliary files that we need to parse, plus it contains
        a lot of the case variables needed as well."""
    def __init__(self, model=None):
        # The next five lines allow you to either pass in an external DataModel, in which case the AV object will
        # assign to that model's variables, or if no model is specified, it will assign to its own variables instead.
        if model is None:
            self.model = self
        else:
            self.model = model
        model = self.model
        self.out = None
        model.term_vel = None
        model.burst_height = None
        model.attack_az = None
        model.aof = None
        model.blast_vol = OrderedDict()
        model.blast_ids = set()
        model.av_file = ''
        model.srf_file = ''
        model.dh_ids = set()
        model.invuln_ids = set()
        self.case_completed = False

    def _parse_av_file(self, line):
        self.model.av_file = self._parse_filename(line, "Couldn't find AV file")

    def _parse_target_center(self, line):
        tokens = line.split(':')[1].strip().strip('\(\)').split(',')
        self.model.tgt_center = float(tokens[0]), float(tokens[1])

    def _parse_term_vel(self, line):
        _, vel_text = line.split(':', 1)
        self.model.term_vel = float(vel_text.split()[0].strip())

    def _parse_burst_height(self, line):
        _, bh = line.split(':')
        self.model.burst_height = float(bh.split()[0])

    def _parse_srf_file(self, line):
        self.model.srf_file = self._parse_filename(line, "Couldn't find surface file")

    def _parse_specific_attack_az(self, line):
        self.model.az_averaging = False
        _, angle_text = line.split(':')
        self.model.attack_az = float(angle_text.split()[0])

    def _parse_averaged_attack_az(self, line):
        self.model.az_averaging = True
        _, angle_text = line.split(':')
        self.model.attack_az = float(angle_text.split()[0])

    def _parse_aof(self, line):
        _, angle_text = line.split(':')
        self.model.aof = float(angle_text.split()[0])

    # noinspection PyUnusedLocal
    def _parse_direct_hit_components(self, line):
        model = self.model
        # the direct hit component list starts after the SRFID header line.
        line = self.out.readline().strip()
        while line != '':
            tokens = line.split()
            model.dh_ids.add(int(tokens[1]))
            line = self.out.readline().strip()

    # noinspection PyUnusedLocal
    def _parse_blast_components(self, line):
        model = self.model
        # the blast component list starts after the CMPID header line.
        line = self.out.readline().strip()
        while line != '':
            tokens = line.split()
            if len(tokens) != 6:
                raise IOError("Can't parse blast components")
            idx = int(tokens[CMPID])
            r1, r2, r3, z1, z2 = (float(tokens[R1]), float(tokens[R2]), float(tokens[R3]), float(tokens[Z1]),
                                  float(tokens[Z2]))

            if not (r1 == 0.0 and r2 == 0.0 and r3 == 0.0 and z1 == 0.0 and z2 == 0.0):
                model.blast_ids.add(idx)
                model.blast_vol[idx] = [r1, r2, r3, z1, z2]
            if r1 == 0.0 and r2 == 0.0 and z1 == 0.0:  # detecting a sphere volume
                line = self.out.readline().strip()  # this line contains the extra "Sphere" field
                if line == "":  # extra insurance in case there's a blank line; exit early
                    break
            line = self.out.readline().strip()

    def _parse_invulnerable_components(self, line):
        model = self.model
        if 'NONE' in line:
            return  # no invulnerable components; leave set empty.
        line = self.out.readline().strip()
        while line != '':  # a blank line indicates end of the list.
            tokens = line.split(':')
            if len(tokens) != 2:
                raise IOError("Can't parse invulnerable components")
            model.invuln_ids.add(int(tokens[1]))
            line = self.out.readline().strip()

    def _parse_kill_file(self, line):
        self.model.kill_file = self._parse_filename(line, "Couldn't find kill definition file")

    def _parse_kill_description(self, line):
        _, kill_desc = line.split(':')
        # this next line trips an error if the kill description value has already been set.
        # Any .out files with multiple matrices have multiple kill description lines.
        if self.model.kill_desc:
            raise ValueError('Cannot read multiple matrices in a single .mtx file')
        self.model.kill_desc = kill_desc.strip()

    # noinspection PyUnusedLocal
    def _parse_case_completed(self, line):
        self.case_completed = True

    # noinspection PyUnusedLocal
    def _parse_filename(self, line, error_msg):
        _, fn = line.split(':', 1)
        fn = fn.strip()
        if fn != "":
            if os.path.exists(fn):
                return fn
            else:
                raise IOError(error_msg)

        # continue reading until we find a filename (we hope)
        while True:
            line = self.out.readline().strip()
            if line != '':
                if os.path.exists(line):
                    return line
                else:
                    raise IOError(error_msg)

    def read(self, out_file):
        """
        Reads output file data.

        :param out_file:
        :return:
        """
        model = self.model
        # Use dictionary for parsing. If the start of the line matches the key, then call the associated value (method)
        # for parsing.
        match = {'TARGET AV FILE': self._parse_av_file,
                 'TARGET CENTER COORDINATES': self._parse_target_center,
                 'TERMINAL VELOCITY': self._parse_term_vel,
                 'BURST HEIGHT': self._parse_burst_height,
                 'TARGET SURFACE FILE': self._parse_srf_file,
                 'ATTACK AZIMUTH - SPECIFIC': self._parse_specific_attack_az,
                 'ATTACK AZIMUTH - AVERAGED': self._parse_averaged_attack_az,
                 'ANGLE OF FALL': self._parse_aof,
                 'INVULNERABLE COMPONENTS': self._parse_invulnerable_components,
                 'CMPID': self._parse_blast_components,
                 'SRFID': self._parse_direct_hit_components,
                 'KILL DEFINITION FILE': self._parse_kill_file,
                 'MATRIX REQUESTED FOR': self._parse_kill_description,
                 'RUN COMPLETE': self._parse_case_completed
                 }
        with open(out_file) as self.out:
            while 1:
                line = self.out.readline()
                if not line:
                    break
                for key in match:
                    if line.lstrip().startswith(key):
                        match[key](line)
                        break
        if self.case_completed:
            # The base filepath is the output directory + the out filename without the extension.
            file_path = os.path.dirname(out_file) + os.path.sep + os.path.splitext(os.path.basename(out_file))[0]
            # append the appropriate extension to the base filepath.
            mtx_file = file_path + '.mtx'
            dtl_file = file_path + '.dtl'
            return model.av_file, model.srf_file, mtx_file, model.kill_file, dtl_file
        else:
            return None, None, None, None, None


class KillNode(object):
    """ Represents a node in the kill file, i.e., an operation with an associated list of items. """
    def __init__(self, op, items):
        self.op = op or ''
        self.items = items or []


class Kill(object):
    """ Kill definition file parser. """
    def __init__(self, model=None):
        # The next five lines allow you to either pass in an external DataModel, in which case the AV object will
        # assign to that model's variables, or if no model is specified, it will assign to its own variables instead.
        if model is None:
            self.model = self
        else:
            self.model = model
        model = self.model
        self.kill = None
        model.num_kills = None
        model.kill_id = None
        model.kill_lines = {}
        model.last_node = {}

    def read(self, kill_file):
        """
        Reads kill definition file data.

        :param kill_file: kill definition filename.
        :return: None
        """
        curr_kill = ''
        curr_key = ''
        model = self.model
        line_no = 0
        with open(kill_file) as self.kill:
            line = self.kill.readline()  # read past top header line
            if not line:
                return
            line = self.kill.readline()
            line_no += 1
            if not line:
                raise IOError('Cannot read kill file.')
            tokens = line.split()
            if len(tokens) != 2:
                raise ValueError('Cannot read number of kills in kill file.')
            model.num_kills = int(tokens[0])
            # parse all kills listed in header looking for the description listed in .out file.
            for i in range(model.num_kills):
                line = self.kill.readline()
                line_no += 1
                if not line:
                    raise IOError('Cannot read component line %d in kill file header.'.format(i))
                tokens = line.split(None, 3)
                description = tokens[-1].strip()
                if description == model.kill_desc:
                    model.kill_id = tokens[0].lower()
            if not model.kill_id and model.kill_desc:
                raise ValueError('Did not find kill ID match between kill definition file and output file.')
            # now parse kill lines
            while True:
                line = self.kill.readline()
                line_no += 1
                if not line:
                    break
                line = line.strip()
                if line == '':
                    continue
                tokens = line.split()
                if tokens[0].startswith('k'):
                    # dict key is "kill, node"
                    key = tokens[0] + ',' + tokens[1]
                    # hold current key and kill in case of '&' continuation line
                    curr_key, curr_kill = key, tokens[0]
                    # store operator and components in KillNode object
                    op, items = tokens[2], [tokens[i] for i in range(3, len(tokens))]
                    model.kill_lines[key] = KillNode(op, items)
                    # hold onto last node so we can later extract all components for that kill in DataModel class
                    model.last_node[tokens[0]] = tokens[1]
                elif tokens[0].startswith('&'):  # continuation line
                    # extend list of stored components in KillNode object
                    model.kill_lines[curr_key].items.extend([tokens[i] for i in range(1, len(tokens))])
                elif tokens[0].startswith('#'):  # comment line
                    continue
                elif tokens[0].isdigit():  # already inside kill w/ consecutive node number
                    # dict key is "kill, node"
                    key = curr_kill + ',' + tokens[0]
                    curr_key = key  # hold current key in case of '&' continuation line
                    # store kill nodes as an object accessed by key
                    model.kill_lines[key] = KillNode(tokens[1], [tokens[i] for i in range(2, len(tokens))])
                    # hold onto last node so we can later extract all components for that kill in DataModel
                    model.last_node[curr_kill] = tokens[0]
                else:
                    raise ValueError('Unrecognized token in kill file, line %d' % line_no)


class Matrix(object):
    """ Matrix file parser. """
    def __init__(self, model=None):
        # The next five lines allow you to either pass in an external DataModel, in which case the AV object will
        # assign to that model's variables, or if no model is specified, it will assign to its own variables instead.
        if model is None:
            self.model = self
        else:
            self.model = model
        model = self.model
        self.mtx = None
        model.cls_range, model.cls_defl = None, None
        model.offset_range, model.offset_defl = None, None
        model.gridlines_range_mid, model.gridlines_defl_mid = None, None
        model.cell_size_range, model.cell_size_defl = None, None
        model.pks = None

    def read(self, mtx_file):
        """
        Reads matrix file data.

        :param mtx_file: Matrix filename.
        :return: None
        """
        model = self.model
        with open(mtx_file) as self.mtx:
            while 1:
                line = self.mtx.readline()
                if not line:
                    raise IOError('Error in matrix file parsing')
                elif line.startswith('<MATRIX HEADER>'):
                    break
            line = self.mtx.readline().strip()
            tokens = line.split(':')
            model.mtx_kill_id = tokens[1].split()[0].lower()  # the kill ID is the first item after the colon
            self.mtx.readline()  # <MATRIX DETAILS> line
            self.mtx.readline()  # <MATRIX DIMENSIONS> line
            line = self.mtx.readline()
            tokens = line.split(',')
            model.cls_range, model.cls_defl = int(tokens[0]), int(tokens[1])
            self.mtx.readline().strip()  # skip <matrix offset coordinate> header
            line = self.mtx.readline().strip()
            tokens = line.split(',')
            model.offset_range, model.offset_defl = float(tokens[0]), float(tokens[1])
            self.mtx.readline().strip()  # skip <matrix gridlines range> header
            line = self.mtx.readline().strip()
            model.gridlines_range = [float(x) for x in line.split()]
            self.mtx.readline().strip()  # skip <matrix gridlines deflection> header
            line = self.mtx.readline().strip()
            model.gridlines_defl = [float(x) for x in line.split()]
            self.mtx.readline().strip()  # skip <matrix pks> header
            # store the PKs in a 2D numpy array for speed.
            model.pks = np.zeros((model.cls_range, model.cls_defl))
            for r in range(model.cls_range):
                line = self.mtx.readline().strip()
                tokens = line.split()
                for d in range(model.cls_defl):
                    model.pks[r, d] = float(tokens[d])


class Detail(object):
    """ Detail file parser. This only parses the full detail file, i.e., burstpoint, component and frag detail.
    Only that version of the file has all the information we need to show frag zones. """
    def __init__(self, model=None, az_averaging=None, attack_az=None, blast_ids=None, dh_ids=None):
        if model is None:
            self.model = self
        else:
            self.model = model
        model = self.model
        if az_averaging is not None:
            model.az_averaging = az_averaging
        if attack_az is not None:
            model.attack_az = attack_az
        if blast_ids is not None:
            model.blast_ids = blast_ids
        if dh_ids is not None:
            model.dh_ids = dh_ids
        self.dtl = None
        self.bp_idx = -1
        self.step = None
        self.az = None
        model.radius = None
        model.eval_center = None
        model.sample_loc = {}
        model.burst_loc = {}
        model.surface_hit = {}
        model.frag_zones = {}
        model.comp_pk = {}
        model.dh_include_frag_effects = None
        model.comp_num = None

    # noinspection PyUnusedLocal
    def _parse_radius(self, line):
        if line.startswith('RADIUS ID'):
            line = self.dtl.readline()
            tokens = line.split(':')
            self.model.radius = float(tokens[1])
        else:
            raise ValueError('RADIUS ID token not found in .dtl file')

    def _parse_evaluation_center(self, line):
        if line.startswith('EVALUATION CENTER'):
            tokens = line.strip().split(':')
            self.model.eval_center = [float(tokens[1]), float(tokens[2]), float(tokens[3])]
        else:
            raise ValueError('EVALUATION CENTER token not found in .dtl file')

    def _parse_direct_hit(self, line):
        if line.startswith('DH PKs include fragments?'):
            self.model.dh_include_frag_effects = True if line.split(':')[1].startswith('T') else False
        else:
            raise ValueError('DH PKs token not found in .dtl file')

    # noinspection PyUnusedLocal
    def _parse_burstpoint(self, line):
        model = self.model
        self.dtl.readline()
        line = self.dtl.readline()
        tokens = line.split(':', 15)
        idx = int(tokens[0])
        # Radial burstpoints steadily increase, so detecting any remedial points (with an index of 1) that follow the
        # radial ones is easy. Remedial points junk up the display.
        # TODO: The only case in which this fails to work is when there are only remedial points (rare), and only one
        # TODO: gets parsed. Since there is no other apparent way to distinguish regular points and remedial ones,
        # TODO: I'm not sure how to distinguish a remedial-point-only case looking at the indices only.
        if idx < self.bp_idx:
            return False
        self.bp_idx = idx
        # add a second azimuth index only after we first access the burstpoint index.
        if not model.sample_loc.get(idx):
            model.sample_loc[idx] = defaultdict(dict)
        if not model.burst_loc.get(idx):
            model.burst_loc[idx] = defaultdict(dict)
        if not model.surface_hit.get(idx):
            model.surface_hit[idx] = defaultdict(dict)
        if not model.frag_zones.get(idx):
            model.frag_zones[idx] = defaultdict(dict)
        if not model.comp_pk.get(idx):
            model.comp_pk[idx] = defaultdict(dict)
        self.az = int(float(tokens[14]))
        model.sample_loc[idx][self.az] = (float(tokens[2]), float(tokens[3]), float(tokens[4]))
        model.burst_loc[idx][self.az] = (float(tokens[8]), float(tokens[9]), float(tokens[10]))
        model.surface_hit[idx][self.az] = int(tokens[12])
        model.frag_zones[idx][self.az] = {}
        model.comp_pk[idx][self.az] = {}
        model.comp_num = 1
        return True

    def _parse_fragmentation(self, line):
        model = self.model
        idx = self.bp_idx
        tokens = line.split(':')
        num_frag_zones = int(tokens[2])
        curr_frag_zone = 0
        zone_info = []
        while curr_frag_zone < num_frag_zones:
            while True:
                line = self.dtl.readline()
                if line.startswith(':FRAG ZONE'):
                    break
            tokens = line.split(':', 3)
            zone_num = int(tokens[2])
            line = self.dtl.readline()
            tokens = line.split(':', 4)
            lower_zone_angle, upper_zone_angle = float(tokens[2]), float(tokens[3])
            zone_info.append((zone_num, lower_zone_angle, upper_zone_angle))
            curr_frag_zone += 1
        model.frag_zones[idx][self.az][model.comp_num] = zone_info
        return True

    # noinspection PyUnusedLocal
    def _parse_component(self, line):
        model = self.model
        self.dtl.readline()
        line = self.dtl.readline()
        tokens = line.split(':', 15)
        idx = self.bp_idx
        cid = model.comp_num
        # identify the correct token for component PK by looking at the DH, blast and frag IDs.
        if cid in model.dh_ids:
            model.comp_pk[idx][self.az][cid] = float(tokens[12])
        elif cid in model.blast_ids:
            model.comp_pk[idx][self.az][cid] = float(tokens[13])
        elif cid in model.frag_ids:
            model.comp_pk[idx][self.az][cid] = float(tokens[14])
        model.comp_num += 1
        return True

    def validate(self, dtl_file):
        """
        Validates detailed output file to make sure it's the full detail version.

        :param dtl_file: Detailed output filename.
        :return: None
        """
        validated = False
        with open(dtl_file) as self.dtl:
            while 1:
                line = self.dtl.readline()
                if not line:
                    break
                elif line.startswith(':FRAGMENTATION'):
                    validated = True
                    break

        return validated

    def read(self, dtl_file):
        """
        Reads detailed output file data.

        :param dtl_file: Detailed output filename.
        :return: None
        """
        # Use dictionary for parsing. If the start of the line matches the key, then call the associated value (method)
        # for parsing.
        match = {'BPNUM': self._parse_burstpoint,
                 ':FRAGMENTATION': self._parse_fragmentation,
                 ':COMPONENT': self._parse_component
                 }
        model = self.model
        model.comp_num = 1
        model.radius = None
        model.eval_center = None
        model.sample_loc = {}
        model.burst_loc = {}
        model.dh_include_frag_effects = None
        model.surface_hit = {}
        model.frag_zones = {}
        model.comp_pk = {}

        with open(dtl_file) as self.dtl:
            while 1:
                line = self.dtl.readline()
                if not line:
                    break
                for key in match:
                    if line.startswith(key):
                        if match[key](line):
                            break
                        else:
                            return
