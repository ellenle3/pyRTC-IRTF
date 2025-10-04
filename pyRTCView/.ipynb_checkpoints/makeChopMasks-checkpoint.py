import argparse
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Button
from astropy.io import fits

FELIX_PIXEL_SCALE = 0.16  # arcsec/pixel
MAX_CHOP = 5  # arcsec

class ChopROISelector:
    def __init__(self, image, masks):
        self.dist_arcsec = None
        self.image = image
        self.image_size = image.shape[0]
        if image.shape[0] != image.shape[1]:
            raise ValueError("Image must be square")
        self.masks = masks 
        self.box_size = masks.shape[1]

        # Figure and axes
        self.fig, self.ax = plt.subplots()
        plt.subplots_adjust(bottom=0.35)
        self.ax.imshow(self.image, cmap='gray')
        self.ax.set_xlim(0, self.image.shape[1])
        self.ax.set_ylim(self.image.shape[0], 0)

        # Bottom axes for text
        self.text_ax = self.fig.add_axes([0, 0, 1, 0.3])
        self.text_ax.axis('off')

        self.boxes = []       # (rect, overlays)
        self.roi_coords = []  # top-left coordinates
        self.current_box_idx = 0
        self.interp_rects = []

        # Initialize first box (red + masks)
        self._init_box(color='red', show_masks=True)

        # OK button
        ax_ok = plt.axes([0.4, 0.02, 0.2, 0.05])
        self.button_ok = Button(ax_ok, 'OK')
        self.button_ok.on_clicked(self.on_ok)

        # Mouse events
        self.cid_press = self.fig.canvas.mpl_connect('button_press_event', self.on_click)
        self.cid_motion = self.fig.canvas.mpl_connect('motion_notify_event', self.on_drag)

    def _init_box(self, color='red', show_masks=True):
        # Start box in the center
        h, w = self.image.shape
        x0 = w // 2 - self.box_size // 2
        y0 = h // 2 - self.box_size // 2

        rect = plt.Rectangle((x0, y0), self.box_size, self.box_size,
                             edgecolor=color, facecolor='none', lw=2)
        self.ax.add_patch(rect)

        overlays = []
        if show_masks:
            cmap_list = ['Reds', 'Blues', 'Greens', 'Purples']
            for i in range(4):
                mask_nan = self.masks[i].astype(float)
                mask_nan[mask_nan == 0] = np.nan
                overlay = self.ax.imshow(mask_nan, cmap=cmap_list[i], alpha=0.6,
                                         vmin=0, vmax=1,
                                         extent=(x0, x0+self.box_size, y0+self.box_size, y0))
                overlay.set_zorder(2)
                overlays.append(overlay)

        self.boxes.append((rect, overlays))
        self.roi_coords.append((x0, y0))

    def _update_box(self, x, y):
        x0 = np.clip(int(x) - self.box_size//2, 0, self.image_size-self.box_size)
        y0 = np.clip(int(y) - self.box_size//2, 0, self.image_size-self.box_size)
        self.roi_coords[self.current_box_idx] = (x0, y0)
        rect, overlays = self.boxes[self.current_box_idx]
        rect.set_xy((x0, y0))
        for overlay in overlays:
            overlay.set_extent((x0, x0+self.box_size, y0+self.box_size, y0))
        self.fig.canvas.draw_idle()

    def on_click(self, event):
        if event.inaxes != self.ax:
            return
        self._update_box(event.xdata, event.ydata)

    def on_drag(self, event):
        if event.inaxes != self.ax or event.button != 1:
            return
        self._update_box(event.xdata, event.ydata)

    def _update_text(self, lines):
        """Show text centered in bottom axes."""
        self.text_ax.clear()
        self.text_ax.axis('off')
        ypos = 0.9
        for line in lines:
            self.text_ax.text(0.5, ypos, line, fontsize=10, color='black',
                              ha='center', va='top')
            ypos -= 0.1
        self.fig.canvas.draw_idle()

    def on_ok(self, event):
        x0, y0 = self.roi_coords[self.current_box_idx]

        if self.current_box_idx == 0:
            # First box selected
            self._update_text([f"Box 1 top-left: ({x0}, {y0})"])
            self.current_box_idx = 1
            self._init_box(color='lime', show_masks=False)
        else:
            # Second box selected
            x1, y1 = self.roi_coords[0]
            x2, y2 = self.roi_coords[1]
            c1 = np.array([x1+self.box_size/2, y1+self.box_size/2])
            c2 = np.array([x2+self.box_size/2, y2+self.box_size/2])
            dist_pix = np.linalg.norm(c2 - c1)
            self.dist_arcsec = dist_pix * FELIX_PIXEL_SCALE

            self._update_text([
                f"Box 1 top-left: ({x1}, {y1})",
                f"Box 2 top-left: ({x2}, {y2})",
                f"Distance: {dist_pix:.2f} px = {self.dist_arcsec:.2f}\""
            ])

            # Draw interpolated boxes
            for rect in self.interp_rects:
                rect.remove()
            self.interp_rects = []

            for pos in np.linspace(c1, c2, args.n):
                x_center, y_center = pos
                x0 = int(x_center - self.box_size/2)
                y0 = int(y_center - self.box_size/2)
                x0 = np.clip(x0, 0, self.image_size-self.box_size)
                y0 = np.clip(y0, 0, self.image_size-self.box_size)
                interp_rect = plt.Rectangle((x0, y0), self.box_size, self.box_size,
                                            edgecolor='cyan', facecolor='none', lw=1)
                self.ax.add_patch(interp_rect)
                self.interp_rects.append(interp_rect)
            self.fig.canvas.draw_idle()

    def make_interpolated_masks(self, n=10):
        interp_masks = np.zeros((n, 4, self.image_size, self.image_size), dtype=self.masks.dtype)
        centers = []
        x1, y1 = self.roi_coords[0]
        x2, y2 = self.roi_coords[1]
        c1 = np.array([x1+self.box_size//2, y1+self.box_size//2])
        c2 = np.array([x2+self.box_size//2, y2+self.box_size//2])

        for idx, t in enumerate(np.linspace(0, 1, n)):
            pos = (1-t)*c1 + t*c2
            x_center, y_center = pos
            x0 = int(x_center - self.box_size//2)
            y0 = int(y_center - self.box_size//2)
            x0 = np.clip(x0, 0, self.image_size-self.box_size)
            y0 = np.clip(y0, 0, self.image_size-self.box_size)
            centers.append((int(x_center), int(y_center)))
            for i in range(4):
                interp_masks[idx, i, y0:y0+self.box_size, x0:x0+self.box_size] = self.masks[i]
        return interp_masks, centers

    def show(self):
        plt.show()
        return self.roi_coords


def save_masks_to_fits(masks, centers, image_size, filename="masks.fits"):
    """Save masks and offsets to a FITS file."""
    cx = image_size // 2
    cy = image_size // 2
    offsets = np.array([(xc - cx, yc - cy) for (xc, yc) in centers], dtype=np.int16)

    hdu_masks = fits.PrimaryHDU(masks.astype('>i8'))
    hdu_offsets = fits.ImageHDU(offsets, name="OFFSETS")

    hdul = fits.HDUList([hdu_masks, hdu_offsets])
    hdul.writeto(filename, overwrite=True)
    print(f"Saved FITS: {filename}")

    # Save A and B positions separately
    hdu_mask_a = fits.PrimaryHDU(masks[0].astype('>i8'))
    hdu_offsets_a = fits.ImageHDU(offsets[0], name="OFFSETS")
    hdul_a = fits.HDUList([hdu_mask_a, hdu_offsets_a])
    fname_a = filename.replace('.fits', '_posA.fits')
    hdul_a.writeto(fname_a, overwrite=True)
    print(f"Saved FITS: {fname_a}")

    hdu_mask_b = fits.PrimaryHDU(masks[1].astype('>i8'))
    hdu_offsets_b = fits.ImageHDU(offsets[1], name="OFFSETS")
    hdul_b = fits.HDUList([hdu_mask_b, hdu_offsets_b])
    fname_b = filename.replace('.fits', '_posB.fits')
    hdul_b.writeto(fname_b, overwrite=True)
    print(f"Saved FITS: {fname_b}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Select two boxes and generate interpolated masks")
    parser.add_argument('image_file', type=str,
                        help='File containing the image to display (FITS or npy)')
    parser.add_argument('--n', type=int, default=15,
                        help='Number of interpolated boxes/masks (default: 15)')
    parser.add_argument('--fout', type=str, default='../IRTF/calib/felixcal/masks_itp.fits',
                        help='Output FITS file to save the interpolated masks')

    args = parser.parse_args()

    fname = args.image_file
    if fname.lower().endswith('.npy'):
        img = np.load(fname)
    elif fname.lower().endswith('.fits'):
        img = fits.getdata(fname)
    else:
        raise ValueError("Image file must be .npy or .fits")

    masks = fits.getdata("subaps2x2_50pix.fits", ext=0)  # shape (4,N,N)
    print(masks.shape)

    roi_tool = ChopROISelector(img, masks)
    coords = roi_tool.show()
    if roi_tool.dist_arcsec is not None and roi_tool.dist_arcsec > MAX_CHOP:
        raise ValueError(f"Chop distance {roi_tool.dist_arcsec:.2f}\" exceeds maximum of {MAX_CHOP}\"")

    interp_masks, centers = roi_tool.make_interpolated_masks(n=args.n)
    print("Interpolated masks shape:", interp_masks.shape)

    save_masks_to_fits(interp_masks, centers, roi_tool.image_size, filename=args.fout)
