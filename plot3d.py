# -*- coding: utf-8 -*-
from numpy import array, full
from PySide import QtGui
import util
from tvtk.api import tvtk
from tvtk.common import configure_input
from mayavi import mlab


"""
Created on Wed Nov 27 10:37:08 2013
"""
__author__ = 'brandon.corfman'
__doc__ = '''
    Plot a target scene using JMAE input and output files.

    The AVs in AVFILE are plotted as a 3D bubble chart at the az & el defined in the output file.
    Vulnerable areas are sized by magnitude, and probabilities of exposure are graded by color
    (full red = 1.0, full green = 0.0).

    Target surfaces are plotted as wireframe quads.
    Blast volumes are plotted as spheres or double cylinders with sphere caps.
'''


######################################################################


class Plotter:
    def __init__(self, title, parent):
        self.parent = parent
        self.title = title
        self.scale_defl, self.scale_range = 0.0, 0.0
        self.plot = None
        self.target = None
        self.model = None
        self.rotation = 0

    def plot_av(self):
        # TODO: plot AVs based on interpolation like JMAE (not just the nearest ones)
        model = self.model
        iaz = model.az_idx
        iel = model.el_idx
        x, y, z, sz, color = [], [], [], [], []
        for i in range(model.num_tables):  # iterates over real component AVs (no dummy components)
            x.append(model.comp_list[i].x)
            y.append(model.comp_list[i].y)
            z.append(model.comp_list[i].z)
            # get the average masses and velocities for the selected azimuth and elevation
            avg_av, avg_pe = 0.0, 0.0
            for ims, _ in enumerate(model.mss):
                for ivl, _ in enumerate(model.vls):
                    avg_av += model.avs[i][iaz][iel][ims][ivl]
                    if model.az_averaging:
                        avg_pe += model.pes[i][iaz][iel][ims][ivl]
            avg_av /= (model.num_ms * model.num_vl)
            if model.az_averaging:
                avg_pe /= (model.num_ms * model.num_vl)
            # sphere size represents average vulnerable areas (relative to each other)
            # sphere color represents average probability of exposure using blue-red colormap (blue=0.0, red=1.0)
            sz.append(avg_av)
            color.append(avg_pe)
        if not model.az_averaging:
            color = [1.0 for _ in range(model.num_tables)]  # red for any by-azimuth AVs, since PEs don't apply.
        pts = mlab.quiver3d([x], [y], [z], [sz], [sz], [sz], name='component AV', colormap='blue-red',
                            scalars=color, mode='sphere')
        pts.module_manager.scalar_lut_manager.reverse_lut = True
        pts.glyph.color_mode = 'color_by_scalar'

    def plot_srf_file(self):
        model = self.model
        fig = mlab.gcf()
        if model.az_averaging:
            cyl = tvtk.CylinderSource(center=model.tgt_center, radius=model.swept_volume_radius,
                                      height=model.srf_max_z + .5,  # slight fudge factor to enclose all top surfaces
                                      resolution=50, capping=True)
            cyl_mapper = tvtk.PolyDataMapper(input_connection=cyl.output_port)
            p = tvtk.Property(opacity=0.65, color=(0.6745, 0.196, 0.3882))  # gypsy pink color, coveted by JJS
            cyl_actor = tvtk.Actor(mapper=cyl_mapper, property=p, position=(0, 0, -model.tgt_center[1]))
            t = tvtk.Transform()
            t.rotate_x(90.0)
            cyl_actor.user_transform = t
            fig.scene.add_actor(cyl_actor)
        else:
            polys = array([[4 * i, 4 * i + 1, 4 * i + 2, 4 * i + 3] for i in range(len(model.surfaces) / 4)])
            poly_obj = tvtk.PolyData(points=model.surfaces, polys=polys)
            self.target = mlab.pipeline.surface(poly_obj, name='target', figure=fig)
            self.target.actor.property.representation = 'wireframe'
            self.target.actor.property.color = (0, 0, 0)

    def plot_matrix_file(self):
        model = self.model
        figure = mlab.gcf()

        # Define rectilinear grid according to the matrix gridlines.
        # Set the single Z coordinate in the elevation array equal to the munition burst height.
        elevations = full(1, model.burst_height)
        x_dim, y_dim, z_dim = len(model.gridlines_range), len(model.gridlines_defl), len(elevations)
        rgrid = tvtk.RectilinearGrid(x_coordinates=model.gridlines_range, y_coordinates=model.gridlines_defl,
                                     z_coordinates=elevations, dimensions=(x_dim, y_dim, z_dim))

        # Extract a plane from the grid for display. This geometry filter may not be needed,
        # but it doesn't hurt anything.
        plane = tvtk.RectilinearGridGeometryFilter(extent=(0, x_dim - 1, 0, y_dim - 1, 0, z_dim - 1))
        configure_input(plane, rgrid)
        rgrid_mapper = tvtk.PolyDataMapper(input_connection=plane.output_port)

        p = tvtk.Property(color=(0, 0, 0))  # color only matters if we are using wireframe, but I left it in for ref.
        wire_actor = tvtk.Actor(mapper=rgrid_mapper, property=p)
        figure.scene.add_actor(wire_actor)  # add rectilinear grid to the scene

        # Grid colors are displayed using an additional array (PKs).
        # T transposes the 2D PK array to match the viewer coordinate system and then
        # ravel() flatten the 2D array to a 1D array for VTK use as scalars.
        rgrid.cell_data.scalars = model.pks.T.ravel()
        rgrid.cell_data.scalars.name = 'pks'
        rgrid.cell_data.update()  # refreshes the grid now that a new array has been added.

        # this method puts the surface in the Mayavi pipeline so the user can change it.
        surf = mlab.pipeline.surface(rgrid, name='matrix')

        # give PK colorbar a range between 0 and 1. The default is to use the min/max values in the array,
        # which would give us a custom range every time and make it harder for the user to consistently identify what
        # the colors mean.
        surf.module_manager.scalar_lut_manager.use_default_range = False
        surf.module_manager.scalar_lut_manager.data_range = array([0., 1.])
        mlab.colorbar(surf, title='Cell Pk', orientation='vertical')

    def plot_blast_volume(self, blast_id):
        model = self.model
        comp = model.comp_list[blast_id - 1]
        v = mlab.gcf()
        t = tvtk.Transform()
        t.rotate_x(90.0)
        r1, r2, r3, z1, z2 = model.blast_vol[blast_id]
        if r1 == 0 or r2 == 0 or z1 == 0:
            # blast sphere
            p = tvtk.Property(opacity=0.25, color=(1, 1, 0))
            sphere = tvtk.SphereSource(center=(0, 0, 0), radius=r3)
            sphere_mapper = tvtk.PolyDataMapper()
            configure_input(sphere_mapper, sphere)
            sphere_actor = tvtk.Actor(mapper=sphere_mapper, property=p)
            sphere_actor.user_transform = t
            v.scene.add_actor(sphere_actor)
            sphere_actor.position = [comp.x, z2 + comp.z, comp.y]  # TODO: check correct sphere rotation
        else:
            # double cylinder
            lower_cyl = tvtk.CylinderSource(center=(0, 0, 0), radius=r1,
                                            height=z1, resolution=50, capping=True)
            cyl_mapper = tvtk.PolyDataMapper()
            configure_input(cyl_mapper, lower_cyl)
            p = tvtk.Property(opacity=0.25, color=(1, 1, 0))
            cyl_actor = tvtk.Actor(mapper=cyl_mapper, property=p)
            cyl_actor.user_transform = t
            v.scene.add_actor(cyl_actor)
            # cx, cy, cz = util.rotate_pt_around_yz_axes(comp.x, comp.y, comp.z, 0.0, model.attack_az)
            cyl_actor.position = [comp.x, (z1 + comp.z) / 2.0 + 0.01, comp.y]

            upper_cyl = tvtk.CylinderSource(center=(0, 0, 0), radius=r2, height=z2 - z1, resolution=50,
                                            capping=False)
            cyl_mapper = tvtk.PolyDataMapper()
            configure_input(cyl_mapper, upper_cyl)
            cyl_actor = tvtk.Actor(mapper=cyl_mapper, property=p)
            cyl_actor.user_transform = t
            v.scene.add_actor(cyl_actor)
            cyl_actor.position = [comp.x, ((z2 - z1) / 2.0) + z1 + comp.z, comp.y]

            cap = tvtk.SphereSource(center=(0, 0, 0), radius=r3, start_theta=0, end_theta=180,
                                    phi_resolution=50)
            cap_mapper = tvtk.PolyDataMapper()
            configure_input(cap_mapper, cap)
            cap_actor = tvtk.Actor(mapper=cap_mapper, property=p)
            cap_actor.user_transform = t
            v.scene.add_actor(cap_actor)
            cap_actor.position = [comp.x, z2 + comp.z, comp.y]

    def plot_munition(self):
        """ Plot an arrow showing direction of incoming munition and display text showing angle of fall,
        attack azimuth and terminal velocity. """
        model = self.model
        fig = mlab.gcf()

        # rotate unit vector into position of munition attack_az and aof
        xv, yv, zv = util.rotate_pt_around_yz_axes(1.0, 0.0, 0.0, model.aof, model.attack_az)
        # position arrow position outside of target, using both maximum radius and matrix offset.
        arrow_distance = model.swept_volume_radius + 5  # fudge to put arrow just outside radius
        xloc, yloc, zloc = util.rotate_pt_around_yz_axes(-arrow_distance, 0.0, 0.0, model.aof, model.attack_az)
        mlab.quiver3d([xloc], [yloc], [zloc + 1.0], [xv], [yv], [zv], color=(1, 1, 1), reset_zoom=False, line_width=15,
                      scale_factor=15, name='munition', mode='arrow', figure=fig)
        format_str = '{0}° AOF\n{1}° attack azimuth\n{2} ft/s terminal velocity'
        mlab.text3d(xloc, yloc, zloc + 6, format_str.format(model.aof, model.attack_az, model.term_vel),
                    color=(1, 1, 1), name='munition-text', figure=fig)

    def plot_data(self, model, blast_id):
        self.model = model
        scene = mlab.get_engine().new_scene()  # create a new scene window every time
        scene.title = self.title
        scene.disable_render = True  # generate scene more quickly by temporarily turning off rendering
        if self.model.pks is not None:
            self.plot_matrix_file()  # matrix can be plotted if it was read in
        self.plot_srf_file()
        if self.model.blast_vol:
            self.plot_blast_volume(blast_id)  # plot blast volume if blast damage was included in output
        self.plot_av()
        self.plot_munition()
        # figure = mlab.gcf()
        # picker = figure.on_mouse_pick(self.pick_callback)
        # picker.tolerance = 0.01 # Decrease the tolerance, so that we can more easily select a precise point
        scene.disable_render = False  # reinstate display
        mlab.view(azimuth=0, elevation=30, distance=250, focalpoint=(0, 0, 29), figure=mlab.gcf())
