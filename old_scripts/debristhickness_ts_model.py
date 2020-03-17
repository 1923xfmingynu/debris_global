#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OVERVIEW: DEBRIS THICKNESS ESTIMATES BASED ON DEM DIFFERENCING BANDS
 Objective: derive debris thickness using an iterative approach that solves for when the modeled melt rate agrees with
 the DEM differencing

If using these methods, cite the following paper:
    Rounce, D.R., King, O., McCarthy, M., Shean, D.E. and Salerno, F. (2018). Quantifying debris thickness of
    debris-covered glaciers in the Everest region of Nepal through inversion of a subdebris melt model,
    Journal of Geophysical Research: Earth Surface, 123(5):1095-1115, doi:10.1029/2017JF004395.

Notes for running the model:
  The model uses relative paths to the input and output.  This was done to make it easier to share the model and not
  have to worry about changing the filenames.  That said, the script needs to be run in Matlab with the current folder
  open to the location of the script.

Assumptions:
 - Slope and aspect of pixel are not changing through time
 - Surface lowering only considers flux divergence and surface mass
   balance
 - Climatic mass balance between Oct 15 - May 15 is zero, i.e., any snow
   that has accumulated has melted

Limitations:
 - Does not account for shading from surrounding terrain
 - Does not account for snowfall thereby potentially overestimating melt
   which would underestimate debris thickness
 - Does not account for changes in debris thickness over time

Files required to run model successfully:
 - DEM (raster)
 - Slope (raster)
 - Aspect (raster)
 - Elevation change (raster)
 - Elevation change (.csv each box with uncertainty)
 - Glacier outline (raster - 1/0 for glacier/non-glacier pixels)
 - Bands/boxes outlines (raster - each pixel is assigned value of box, 0 represents pixel outside of box)
 - Emergence velocity (.csv each box with uncertainty)
 - Meteorological Data (.csv)

Other important input data
 - Lat/Long starting point (center of upper left pixel)
 - Lat/Long pixel resolution in degrees
 - Number of Monte Carlo simulations
 - Time step (input.delta_t)
 - Number of years modeled
 - Number of iterations (will affect thickness resolution)

Monte Carlo simulation allows uncertainty to be incorporated into model performance.  The debris properties that are
 considered are: (1) albedo, (2) surface roughness, and (3) thermal conductivity. Additional uncertainty regarding
 products are: (4) error associated with elevation change.
"""

# Built-in libaries
import argparse
import collections
import datetime
import multiprocessing
import os
import time
# External libraries
#import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
#import xarray as xr
# Local libraries
import kennicott_input as input


#%% FUNCTIONS
def getparser():
    """
    Use argparse to add arguments from the command line

    Parameters
    ----------
    batchno (optional) : int
        batch number used to differentiate output on supercomputer
    batches (optional) : int
        total number of batches based on supercomputer
    num_simultaneous_processes (optional) : int
        number of cores to use in parallels
    option_parallels (optional) : int
        switch to use parallels or not
    debug (optional) : int
        Switch for turning debug printing on or off (default = 0 (off))

    Returns
    -------
    Object containing arguments and their respective values.
    """
    parser = argparse.ArgumentParser(description="run simulations from gcm list in parallel")
    # add arguments
    parser.add_argument('-batchno', action='store', type=int, default=0,
                        help='Batch number used to differentiate output on supercomputer')
    parser.add_argument('-batches', action='store', type=int, default=1,
                        help='Total number of batches (nodes) for supercomputer')
    parser.add_argument('-num_simultaneous_processes', action='store', type=int, default=4,
                        help='number of simultaneous processes (cores) to use')
    parser.add_argument('-option_parallels', action='store', type=int, default=1,
                        help='Switch to use or not use parallels (1 - use parallels, 0 - do not)')
    parser.add_argument('-debug', action='store', type=int, default=0,
                        help='Boolean for debugging to turn it on or off (default 0 is off')
    return parser


def solar_calcs_NOAA(year, julian_day_of_year, time_frac, longitude_deg, latitude_deg, nsteps):
    """ NOAA calculations to determine the position of the sun and distance to sun

    Sun position based on NOAA solar calculator
    Earth-sun distance based on Stamnes (2015)

    Parameters
    ----------
    year : np.array
        array of the year associated with each time step
    julian_day_of_year : np.array
        julian day of year associated with each time step
    time_frac : np.array
        time (hour + minute / 60) of each time step
    longitude_deg : float
        longitude in degrees
    latitude_deg : float
        latitude in degrees

    Returns
    -------
    SolarZenithAngleCorr_rad : np.array
        Solar zenith angle [radians] corrected for atmospheric refraction
    SolarAzimuthAngle_rad : np.array
        Solar azimuth angle [radians] based on degrees clockwise from north
    rm_r2 : np.array
        Squared mean earth-sun distance normalized by instantaneous earth-sun distance
    """
    julianday_NOAA = np.zeros((nsteps))
    julianCentury = np.zeros((nsteps))
    GeomMeanLongSun_deg = np.zeros((nsteps))
    GeomMeanLongSun_rad = np.zeros((nsteps))
    GeomMeanAnomSun_deg = np.zeros((nsteps))
    GeomMeanAnomSun_rad = np.zeros((nsteps))
    EccentEarthOrbit = np.zeros((nsteps))
    SunEqofCtr = np.zeros((nsteps))
    SunTrueLong_deg = np.zeros((nsteps))
    SunAppLong_deg = np.zeros((nsteps))
    SunAppLong_rad = np.zeros((nsteps))
    MeanObliqEcliptic_deg = np.zeros((nsteps))
    ObliqCorr_deg = np.zeros((nsteps))
    ObliqCorr_rad = np.zeros((nsteps))
    SunDeclin_deg = np.zeros((nsteps))
    SunDeclin_rad = np.zeros((nsteps))
    VarY = np.zeros((nsteps))
    EqofTime = np.zeros((nsteps))
    TrueSolarTime = np.zeros((nsteps))
    HourAngle_deg = np.zeros((nsteps))
    HourAngle_rad = np.zeros((nsteps))
    SolarZenithAngle_deg = np.zeros((nsteps))
    SolarZenithAngle_rad = np.zeros((nsteps))
    SolarElevationAngle_deg = np.zeros((nsteps))
    SolarElevationAngle_rad = np.zeros((nsteps))
    ApproxAtmosRefrac_deg = np.zeros((nsteps))
    SolarElevationAngleCorr_deg = np.zeros((nsteps))
    SolarZenithAngleCorr_deg = np.zeros((nsteps))
    SolarZenithAngleCorr_rad = np.zeros((nsteps))
    SolarAzimuthAngle_deg = np.zeros((nsteps))
    SolarAzimuthAngle_rad = np.zeros((nsteps))
    rm_r2 = np.zeros((nsteps))

    # Julian day
    #  +1 accounts for the fact that day 1 is January 1, 1900
    #  2415018.5 converts from 1900 to NOAA Julian day of year
    julianday_NOAA = (np.floor(365.25*(year-1900)+1) + julian_day_of_year + (time_frac-input.timezone )/24 +
                      2415018.5)
    # Julian Century
    julianCentury = (julianday_NOAA-2451545) / 36525
    # Geom Mean Long Sun
    GeomMeanLongSun_deg = (280.46646 + julianCentury * (36000.76983 + julianCentury*0.0003032)) % 360
    GeomMeanLongSun_rad = GeomMeanLongSun_deg * np.pi/180
    # Geom Mean Anom Sun
    GeomMeanAnomSun_deg = 357.52911 + julianCentury * (35999.05029 - 0.0001537*julianCentury)
    GeomMeanAnomSun_rad = GeomMeanAnomSun_deg * np.pi/180
    # Eccent Earth Orbit
    EccentEarthOrbit = 0.016708634 - julianCentury * (0.000042037 + 0.0000001267*julianCentury)
    # Sun Eq of Ctr
    SunEqofCtr = (np.sin(GeomMeanAnomSun_rad) * (1.914602 - julianCentury * (0.004817 + 0.000014*julianCentury)) +
                  np.sin(2 * GeomMeanAnomSun_rad) * (0.019993 - 0.000101*julianCentury) +
                  np.sin(3 * GeomMeanAnomSun_rad) * 0.000289)
    # Sun True Long
    SunTrueLong_deg = GeomMeanLongSun_deg + SunEqofCtr
    # Sun True Anom
    #SunTrueAnom_deg = GeomMeanAnomSun_deg + SunEqofCtr
    # Sun Rad Vector [AUs]
    #SunRadVector = ((1.000001018 * (1 - EccentEarthOrbit * EccentEarthOrbit)) /
    #                (1 + EccentEarthOrbit * np.cos(SunTrueAnom_rad)))
    # Sun App Long
    SunAppLong_deg = SunTrueLong_deg - 0.00569 - 0.00478 * np.sin((125.04 - 1934.136*julianCentury) * np.pi/180)
    SunAppLong_rad = SunAppLong_deg * np.pi/180
    # Mean Obliq Ecliptic
    MeanObliqEcliptic_deg = (23 + (26 + ((21.448 - julianCentury * (46.815 + julianCentury * (0.00059 -
                             julianCentury * 0.001813)))) / 60) / 60)
    # Obliq Corr
    ObliqCorr_deg = MeanObliqEcliptic_deg + 0.00256 * np.cos((125.04 - 1934.136*julianCentury) * np.pi/180)
    ObliqCorr_rad = ObliqCorr_deg * np.pi/180
    # Sun Rt Ascen
    #SunRtAscen_deg = (180/np.pi * np.arctan((np.cos(ObliqCorr_rad) * np.sin(SunAppLong_rad)) /
    #                                        np.cos(SunAppLong_rad)))
    # Sun Declin
    SunDeclin_deg = 180/np.pi * np.arcsin(np.sin(ObliqCorr_rad) * np.sin(SunAppLong_rad))
    SunDeclin_rad = SunDeclin_deg * np.pi/180
    # VarY
    VarY = np.tan(ObliqCorr_deg / 2 * np.pi/180) * np.tan(ObliqCorr_deg / 2 * np.pi/180)
    # Eq of Time [min]
    EqofTime = (4 * 180/np.pi * (VarY * np.sin(2 * GeomMeanLongSun_rad) - 2 * EccentEarthOrbit *
                np.sin(GeomMeanAnomSun_rad) + 4 * EccentEarthOrbit * VarY * np.sin(GeomMeanAnomSun_rad) *
                np.cos(2 * GeomMeanLongSun_rad) - 0.5 * VarY * VarY * np.sin(4 * GeomMeanLongSun_rad) - 1.25 *
                EccentEarthOrbit * EccentEarthOrbit * np.sin(2 * GeomMeanAnomSun_rad)))
    # True Solar Time [min]
    TrueSolarTime = (time_frac*60*1440 + time_frac*60 + EqofTime + 4*longitude_deg - 60*input.timezone) % 1440
    # Hour Angle
    HourAngle_deg[TrueSolarTime/4 < 0] = TrueSolarTime[TrueSolarTime/4 < 0] / 4 + 180
    HourAngle_deg[TrueSolarTime/4 >= 0] = TrueSolarTime[TrueSolarTime/4 >= 0] / 4 - 180
    HourAngle_rad = HourAngle_deg * np.pi/180
    # Solar Zenith Angle (deg)
    SolarZenithAngle_deg = (180/np.pi * np.arccos(np.sin(latitude_deg * np.pi/180) * np.sin(SunDeclin_rad) +
                            np.cos(latitude_deg * np.pi/180) * np.cos(SunDeclin_rad) * np.cos(HourAngle_rad)))
    SolarZenithAngle_rad = SolarZenithAngle_deg * np.pi/180
    # Solar Elevation Angle (deg)
    SolarElevationAngle_deg = 90 - SolarZenithAngle_deg
    SolarElevationAngle_rad = SolarElevationAngle_deg * np.pi/180
    # Approx Atmospheric Refraction (deg)
    ApproxAtmosRefrac_deg = -20.772 / np.tan(SolarElevationAngle_rad)
    ApproxAtmosRefrac_deg[SolarElevationAngle_deg > 85] = 0
    mask = [(SolarElevationAngle_deg > 5) & (SolarElevationAngle_deg <= 85)]
    ApproxAtmosRefrac_deg[mask] = (
            58.1 / np.tan(SolarElevationAngle_rad[mask]) - 0.07 / ((np.tan(SolarElevationAngle_rad[mask]))**3) +
            0.000086 / ((np.tan(SolarElevationAngle_rad[mask]))**5))
    mask = [(SolarElevationAngle_deg > -0.575) & (SolarElevationAngle_deg <= 5)]
    ApproxAtmosRefrac_deg[mask] = (
            1735 + SolarElevationAngle_deg[mask] * (-518.2 + SolarElevationAngle_deg[mask] *
            (103.4 + SolarElevationAngle_deg[mask] * (-12.79 + SolarElevationAngle_deg[mask]*0.711))))
    ApproxAtmosRefrac_deg = ApproxAtmosRefrac_deg / 3600
    # Solar Elevation Correct for Atm Refraction
    SolarElevationAngleCorr_deg = SolarElevationAngle_deg + ApproxAtmosRefrac_deg
    # Solar Zenith Angle Corrected for Atm Refraction
    SolarZenithAngleCorr_deg = 90 - SolarElevationAngleCorr_deg
    SolarZenithAngleCorr_rad = SolarZenithAngleCorr_deg * np.pi/180
    # Solar Azimuth Angle (deg CW from N)
    SolarAzimuthAngle_deg[HourAngle_deg > 0] = (
            ((180/np.pi * (np.arccos(((np.sin(latitude_deg * np.pi/180) *
              np.cos(SolarZenithAngle_rad[HourAngle_deg > 0])) - np.sin(SunDeclin_rad[HourAngle_deg > 0])) /
              (np.cos(latitude_deg * np.pi/180) * np.sin(SolarZenithAngle_rad[HourAngle_deg > 0])))) + 180) / 360 -
             np.floor((180/np.pi * (np.arccos(((np.sin(latitude_deg * np.pi/180) *
             np.cos(SolarZenithAngle_rad[HourAngle_deg > 0])) - np.sin(SunDeclin_rad[HourAngle_deg > 0])) /
             (np.cos(latitude_deg * np.pi/180) * np.sin(SolarZenithAngle_rad[HourAngle_deg > 0])))) + 180) / 360))
            * 360)
    SolarAzimuthAngle_deg[HourAngle_deg <= 0] = (
            ((540 - 180/np.pi * (np.arccos(((np.sin(latitude_deg * np.pi/180) *
              np.cos(SolarZenithAngle_rad[HourAngle_deg <= 0])) - np.sin(SunDeclin_rad[HourAngle_deg <= 0])) /
              (np.cos(latitude_deg * np.pi/180) * np.sin(SolarZenithAngle_rad[HourAngle_deg <= 0]))))) / 360 -
             np.floor((540 - 180/np.pi * (np.arccos(((np.sin(latitude_deg * np.pi/180) *
             np.cos(SolarZenithAngle_rad[HourAngle_deg <= 0])) - np.sin(SunDeclin_rad[HourAngle_deg <= 0])) /
             (np.cos(latitude_deg * np.pi/180) * np.sin(SolarZenithAngle_rad[HourAngle_deg <= 0]))))) / 360)) * 360)
    SolarAzimuthAngle_rad = SolarAzimuthAngle_deg * np.pi/180
    # Distance from sun based on eccentricity of orbit (r/rm)^2 based on Stamnes (2015)
    # Day number [radians]
    dn_rad = julian_day_of_year * 2 * np.pi / 365
    rm_r2 = (1 / (1.000110 + 0.034221 * np.cos(dn_rad) + 0.001280 * np.sin(dn_rad) + 0.000719 *
                  np.cos(2 * dn_rad) + 0.000077 * np.sin(2 * dn_rad)))**2
    return SolarZenithAngleCorr_rad, SolarAzimuthAngle_rad, rm_r2


def CrankNicholson(Td, Tair, i, debris_thickness, N, h, C, a_Crank, b_Crank, c_Crank, d_Crank, A_Crank, S_Crank):
    """ Run Crank-Nicholson scheme to obtain debris temperature

    Parameters
    ----------
    Td : np.array
        debris temperature [k] (rows = internal layers, columns = timestep)
    Tair : np.array
        air temperature [K]
    i : int
        step number
    debris_thickness : float
        debris thickness [m]
    N : int
        number of layers
    h : float
        height of debris layers [m]
    C : float
        constant defined by Reid and Brock (2010) for Crank-Nicholson Scheme
    a_Crank,

    Returns
    -------
    Td : np.array
        updated debris temperature [k] (rows = internal layers, columns = timestep)
    """
    # Calculate temperature profile in the debris
    # For t = 0, which is i = 1, assume initial condition of linear temperature profile in the debris
    if i == 0:
        Td_gradient = (Td[0,0] - Td[N-1,0])/debris_thickness

        # CODE IMPROVEMENT HERE: TD CALCULATION SKIPPED ONE
        for j in np.arange(1,N-1):
            Td[j,0] = Td[0,0] - (j*h)*Td_gradient

    else:
        # Perform Crank-Nicholson Scheme
        for j in np.arange(1,N-1):
            # Equations A8 in Reid and Brock (2010)
            a_Crank[j,i] = C
            b_Crank[j,i] = 2*C+1
            c_Crank[j,i] = C

            # Equations A9 in Reid and Brock (2010)
            if j == 1:
                d_Crank[j,i] = C*Td[0,i] + C*Td[0,i-1] + (1-2*C)*Td[j,i-1] + C*Td[j+1,i-1]
            elif j < (N-2):
                d_Crank[j,i] = C*Td[j-1,i-1] + (1-2*C)*Td[j,i-1] + C*Td[j+1,i-1]
            elif j == (N-2):
                d_Crank[j,i] = 2*C*Td[N-1,i] + C*Td[N-3,i-1] + (1-2*C)*Td[N-2,i-1]
            # note notation:
            #  "i-1" refers to the past
            #  "j-1" refers to the cell above it
            #  "j+1" refers to the cell below it


            # Equations A10 and A11 in Reid and Brock (2010)
            if j == 1:
                A_Crank[j,i] = b_Crank[j,i]
                S_Crank[j,i] = d_Crank[j,i]
            else:
                A_Crank[j,i] = b_Crank[j,i] - a_Crank[j,i] / A_Crank[j-1,i] * c_Crank[j-1,i]
                S_Crank[j,i] = d_Crank[j,i] + a_Crank[j,i] / A_Crank[j-1,i] * S_Crank[j-1,i]

        # Equations A12 in Reid and Brock (2010)
        for j in np.arange(N-2,0,-1):
            if j == (N-2):
                Td[j,i] = S_Crank[j,i] / A_Crank[j,i]
            else:
                Td[j,i] = 1 / A_Crank[j,i] * (S_Crank[j,i] + c_Crank[j,i] * Td[j+1,i])
    return Td


def calc_surface_fluxes(Td_i, Tair_i, RH_AWS_i, u_AWS_i, Sin_i, Lin_AWS_i, Rain_AWS_i, snow_i, P, Albedo, k,
                        a_neutral_debris, h, dsnow_t0, tsnow_t0, snow_tau_t0, ill_angle_rad_i, a_neutral_snow,
                        debris_thickness,
                        option_snow=0, option_snow_fromAWS=0):
    """ Calculate surface energy fluxes for timestep i

    Snow model uses a modified version of Tarboten and Luce (1996) to compute fluxes
      - Sin calculated above, not with their local slope and illumination corrections though
        they are likely similar
      - Ground heat flux is computed from the debris, not using their estimates from diurnal
        soil temperatures
      - Do not use their temperature threshold for snowfall, but use set value
      - For P_flux, we do not include the snow fall component because it alters the cold content of the snow pack
        therefore we don't want to double count this energy
      - Do not account for wind redistribution of snow, which they state is site specific
      - Do not iterate to solve snow temperature, but do a depth average
      - Solve for the thermal conductivity at the debris/ice interface using the depth of snow and debris height

    Limitation:
      - If allow all negative energy to warm up the snowpack and the snowpack is very thin (< 1 cm), then the
        change in temperature can be extreme (-10 to -1000s of degrees), which is unrealistic.
        More realistic is that the snowpack may change its temperature and the remaining energy will be
        transferred to also cool the debris layer. Set maximum temperature change of the snow pack during any given
        time step to 1 degC.

    Note: since partitioning rain into snow, units are automatically m w.e.
          hence, the density of snow is not important

    Future work:
      - Currently, the debris/ice interface is set to 273.15.
        This is fine during the ablation season; however, when the debris freezes in the winter
      - Snow melt water should theoretically percolate into the debris and transfer energy

    Parameters
    ----------
    Td_i : np.array
        debris temperature
    Tair_i, RH_AWS_i, u_AWS_i, Sin_i, Lin_AWS_i, Rain_AWS_i, snow_i : floats
        meteorological data
    P : float
        pressure [Pa]
    Albedo, k, a_neutral_debris : floats
        debris albedo, thermal conductivity, and turbulent heat flux transfer coefficient (from surface roughness)
    h : float
        debris layer height [m]
    dsnow_t0, tsnow_t0, snow_tau_t0
        snow depth, temperature and dimensionless age at start of time step before any snow or melt has occurred
    ill_angle_rad_i : float
        solar illumination angle used to adjust snow albedo
    a_neutral_snow : float
        snow turbulent heat flux transfer coefficient (based on surface roughness)
    option_snow : int
        switch to use snow model (1) or not (0)
    option_snow_fromAWS : int
        switch to use snow depth (1) instead of snow fall (0)

    Returns
    -------
    F_Ts_i, Rn_i, LE_i, H_i, P_flux_i, Qc_i : floats
        Energy fluxes [W m-2]
    dF_Ts_i, dRn_i, dLE_i, dH_i, dP_flux_i, dQc_i : floats
        Derivatives of energy fluxes
    dsnow_i : float
        Snow depth [mwe] at end of time step
    tsnow_i : float
        Snow temperature at end of time step
    snow_tau_i : float
        Non-dimensional snow age at end of time step
    """
    # Snow depth [m w.e.]
    dsnow_i = dsnow_t0 + snow_i
    snow_tau_i = snow_tau_t0
    tsnow_i = 0

    # First option: Snow depth is based on snow fall, so need to melt snow
    if dsnow_i > 0 and option_snow==1 and option_snow_fromAWS == 0:
        tsnow_i = (dsnow_t0 * tsnow_t0 + snow_i * Tair_i) / dsnow_i

        # Thermal conductivity at debris/snow interface assuming conductance resistance is additive
        #  estimating the heat transfer through dsnow_eff layer of snow and h_eff layer of debris
        # Tarboten and Luce (1996) use effective soil depth of 0.4 m for computing the ground heat transfer
        if debris_thickness < 0.4:
            h_eff = debris_thickness
        else:
            h_eff = 0.4
        if dsnow_i < 0.4:
            dsnow_eff = dsnow_i
        else:
            dsnow_eff = 0.4
        k_snow_interface = (h_eff + dsnow_eff) / (dsnow_eff/input.k_snow + h_eff/k)
        # Previously estimating it based on equal parts
        #k_snow_interface = h / ((0.5 * h) / input.k_snow + (0.5*h) / k)

        # Density of air (dry) based on pressure (elevation) and temperature
        #  used in snow calculations, which has different parameterization of turbulent fluxes
        #  compared to the debris
        density_air = P / (287.058 * Tair_i)

        # Albedo
        # parameters representing grain growth due to vapor diffusion (r1), additional effect near
        #  and at freezing point due to melt and refreeze (r2), and the effect of dirt and soot (r3)
        snow_r1 = np.exp(5000 * (1 / 273.16 - 1 / tsnow_i))
        snow_r2 = np.min([snow_r1**10, 1])
        snow_r3 = 0.03 # change to 0.01 if in Antarctica
        # change in non-dimensional snow surface age
        snow_tau_i += (snow_r1 + snow_r2 + snow_r3) / input.snow_tau_0 * input.delta_t
        # new snow affect on snow age
        if snow_i > 0.01:
            snow_tau_i = 0
        elif snow_i > 0:
            snow_tau_i = snow_tau_i * (1 - 100 * snow_i)
        # snow age
        snow_age = snow_tau_i / (1 + snow_tau_i)
        # albedo as a function of snow age and band
        albedo_vd = (1 - input.snow_c_v * snow_age) * input.albedo_vo
        albedo_ird = (1 - input.snow_c_ir * snow_age) * input.albedo_iro
        # increase in albedo based on illumination angle
        #  illumination angle measured relative to the surface normal
        if np.cos(ill_angle_rad_i) < 0.5:
            b_ill = 2
            f_psi = 1/b_ill * ((1 + b_ill) / (1 + 2 * b_ill * np.cos(ill_angle_rad_i)) - 1)
        else:
            f_psi = 0
        albedo_v = albedo_vd + 0.4 * f_psi * (1 - albedo_vd)
        albedo_ir = albedo_ird + 0.4 * f_psi * (1 - albedo_ird)
        albedo_snow = np.mean([albedo_v, albedo_ir])
        # Adjustments to albedo
        # ensure albedo is within bounds
        if albedo_snow > 1:
            albedo_snow = 1
        elif albedo_snow < 0:
            albedo_snow = 0
        # if snow less than 0.1 m, then underlying debris influences albedo
        if dsnow_i < 0.1:
            r_adj = (1 - dsnow_i/0.1)*np.exp(dsnow_i / (2*0.1))
            albedo_snow = r_adj * Albedo + (1 - r_adj) * albedo_snow

        # Snow Energy Balance
        Rn_snow = (Sin_i * (1 - albedo_snow) + input.emissivity_snow * (Lin_AWS_i -
                   (input.stefan_boltzmann * tsnow_i**4)))
        H_snow = a_neutral_snow * density_air * input.cA * u_AWS_i * (Tair_i - tsnow_i)
        # Vapor pressure above snow assumed to be saturated
        # Vapor pressure (e, Pa) computed using Clasius-Clapeyron Equation and Relative Humidity
        #  611 is the vapor pressure of ice and liquid water at melting temperature (273.15 K)
        eZ_Saturated = 611 * np.exp(input.Lv / input.R_const * (1 / 273.15 - 1 / Tair_i))
        eZ = RH_AWS_i * eZ_Saturated
        # Vapor pressure of snow based on temperature (Colbeck, 1990)
        e_snow = input.eS_snow * np.exp(2838 * (tsnow_i - 273.15) / (0.4619 * tsnow_i * 273.15))
        if e_snow > input.eS_snow:
            e_snow = input.eS_snow
        LE_snow = 0.622 * input.Ls / (input.Rd * Tair_i) * a_neutral_snow * u_AWS_i * (eZ - e_snow)
        Pflux_snow = (Rain_AWS_i * (input.Lf * input.density_water + input.cW * input.density_water *
                                    (np.max([273.15, Tair_i]) - 273.15)) / input.delta_t)
        Qc_snow_debris = k_snow_interface * (Td_i[0] - tsnow_i)/h

        # Net energy available for snow depends on latent heat flux
        # if Positive LE: Air > snow vapor pressure (condensation/resublimation)
        #  energy released and available to melt the snow (include LE in net energy)
        if LE_snow > 0:
            Fnet_snow = Rn_snow + H_snow + LE_snow + Pflux_snow + Qc_snow_debris
            snow_sublimation = 0
        # if Negative LE: Air < snow vapor pressure (sublimation/evaporation)
        #  energy consumed and snow sublimates (do not include LE in net energy)
        else:
            Fnet_snow = Rn_snow + H_snow + Pflux_snow + Qc_snow_debris
            # Snow sublimation [m w.e.]
            snow_sublimation = -1 * LE_snow / (input.density_water * input.Lv) * input.delta_t

        # Cold content of snow [W m2]
        Qcc_snow = input.cSnow * input.density_water * dsnow_i * (273.15 - tsnow_i) / input.delta_t

        # Max energy spent cooling snowpack based on 1 degree temperature change
        Qcc_snow_neg1 = -1 * input.cSnow * input.density_water * dsnow_i / input.delta_t

        # If Fnet_snow is positive and greater than cold content, then energy is going to warm the
        # snowpack to melting point and begin melting the snow.
        if Fnet_snow > Qcc_snow:
            # Snow warmed up to melting temperature
            tsnow_i = 273.15
            Fnet_snow -= Qcc_snow
            Fnet_snow2debris = 0
        elif Fnet_snow < Qcc_snow_neg1:
            # Otherwise only changes the temperature in the snowpack and the debris
            # limit the change in snow temperature
            tsnow_i -= 1
            Fnet_snow2debris = Fnet_snow - Qcc_snow_neg1
            Fnet_snow = 0
        else:
            # Otherwise only changes the temperature
            tsnow_i += Fnet_snow / (input.cSnow * input.density_water * dsnow_i) * input.delta_t
            Fnet_snow = 0
            Fnet_snow2debris = 0

        # Snow melt [m snow] with remaining energy, if any
        snow_melt_energy = Fnet_snow / (input.density_water * input.Lf) * input.delta_t

        # Total snow melt
        snow_melt = snow_melt_energy + snow_sublimation

        # Snow depth [m w.e.]
        dsnow_i -= snow_melt
        if dsnow_i < 0:
            dsnow_i = 0
        if dsnow_i == 0:
            snow_tau_i = 0

        # Solve for temperature in debris
        #  Rn, LE, H, and P equal 0
        Rn_i = 0
        LE_i = 0
        H_i = 0
        Qc_i = k * (Td_i[1] - Td_i[0]) / h
        P_flux_i = 0
        Qc_snow_i = -Qc_snow_debris
        F_Ts_i = Rn_i + LE_i + H_i + Qc_i + P_flux_i + Qc_snow_i  + Fnet_snow2debris

        dRn_i = 0
        dLE_i = 0
        dH_i = 0
        dQc_i = -k/h
        dP_flux_i = 0
        dQc_snow_i = -k_snow_interface/h
        dF_Ts_i = dRn_i + dLE_i + dH_i + dQc_i + dP_flux_i + dQc_snow_i

    # Second option: Snow depth is prescribed from AWS, so don't need to melt snow
    elif dsnow_i > 0 and option_snow==1 and option_snow_fromAWS == 1:
        dsnow_i = snow_i
        tsnow_i = Tair_i
        if tsnow_i > 273.15:
            tsnow_i = 273.15

        # Thermal conductivity at debris/snow interface assuming conductance resistance is additive
        #  estimating the heat transfer through dsnow_eff layer of snow and h_eff layer of debris
        # Tarboten and Luce (1996) use effective soil depth of 0.4 m for computing the ground heat transfer
        if debris_thickness < 0.4:
            h_eff = debris_thickness
        else:
            h_eff = 0.4
        if dsnow_i < 0.4:
            dsnow_eff = dsnow_i
        else:
            dsnow_eff = 0.4
        k_snow_interface = (h_eff + dsnow_eff) / (dsnow_eff/input.k_snow + h_eff/k)

        Qc_snow_debris = k_snow_interface * (Td_i[0] - tsnow_i)/h

        # Solve for temperature in debris
        #  Rn, LE, H, and P equal 0
        Rn_i = 0
        LE_i = 0
        H_i = 0
        Qc_i = k * (Td_i[1] - Td_i[0]) / h
        P_flux_i = 0
        Qc_snow_i = -Qc_snow_debris
        Fnet_snow2debris = 0
        F_Ts_i = Rn_i + LE_i + H_i + Qc_i + P_flux_i + Qc_snow_i

        dRn_i = 0
        dLE_i = 0
        dH_i = 0
        dQc_i = -k/h
        dP_flux_i = 0
        dQc_snow_i = -k_snow_interface/h
        dF_Ts_i = dRn_i + dLE_i + dH_i + dQc_i + dP_flux_i + dQc_snow_i

    else:
        # Debris-covered glacier Energy Balance (no snow)
        if Rain_AWS_i > 0:
            # Vapor pressure (e, Pa) computed using Clasius-Clapeyron Equation and Relative Humidity
            #  611 is the vapor pressure of ice and liquid water at melting temperature (273.15 K)
            # if raining, assume the surface is saturated
            eS_Saturated = 611 * np.exp(-input.Lv / input.R_const * (1 / Td_i[0] - 1 / 273.15))
            eS = eS_Saturated
            eZ_Saturated = 611 * np.exp(-input.Lv / input.R_const * (1 / Tair_i - 1 / 273.15))
            eZ = RH_AWS_i * eZ_Saturated
            LE_i = (0.622 * input.density_air_0 / input.P0 * input.Lv * a_neutral_debris * u_AWS_i
                    * (eZ -eS))
        else:
            LE_i = 0
        Rn_i = Sin_i * (1 - Albedo) + input.emissivity * (Lin_AWS_i - (5.67e-8 * Td_i[0]**4))
        H_i = (input.density_air_0 * (P / input.P0) * input.cA * a_neutral_debris * u_AWS_i *
               (Tair_i - Td_i[0]))
        P_flux_i = input.density_water * input.cW * Rain_AWS_i / input.delta_t * (Tair_i - Td_i[0])
        Qc_i = k * (Td_i[1] - Td_i[0]) / h
        F_Ts_i = Rn_i + LE_i + H_i + Qc_i + P_flux_i

        # Derivatives
        if Rain_AWS_i > 0:
            dLE_i = (-0.622 * input.density_air_0 / input.P0 * input.Lv * a_neutral_debris *
                     u_AWS_i * 611 * np.exp(-input.Lv / input.R_const * (1 / Td_i[0] - 1 / 273.15))
                     * (input.Lv / input.R_const * Td_i[0]**-2))
        else:
            dLE_i = 0
        dRn_i = -4 * input.emissivity * 5.67e-8 * Td_i[0]**3
        dH_i = -1 * input.density_air_0 * P / input.P0 * input.cA * a_neutral_debris * u_AWS_i
        dP_flux_i = -input.density_water * input.cW * Rain_AWS_i/ input.delta_t
        dQc_i = -k / h
        dF_Ts_i = dRn_i + dLE_i + dH_i + dQc_i + dP_flux_i

    return (F_Ts_i, Rn_i, LE_i, H_i, P_flux_i, Qc_i, dF_Ts_i, dRn_i, dLE_i, dH_i, dP_flux_i, dQc_i,
            dsnow_i, tsnow_i, snow_tau_i)


if __name__ == '__main__':
    time_start = time.time()
    parser = getparser()
    args = parser.parse_args()

    if args.debug == 1:
        debug = True
    else:
        debug = False

    time_start = time.time()

    # Date of start of simulation
    date_start = datetime.datetime.today().strftime('%Y%m%d')

    # ===== Meteorological data =====
    met_data = np.genfromtxt(input.met_data_fullfn, delimiter=',', skip_header=1)
    met_data = met_data[input.start_idx:input.end_idx,:]
    long_deg = input.lon_AWS_deg
    lat_deg = input.lat_AWS_deg
    Slope_AWS_rad = input.slope_AWS_deg*(np.pi/180)
    Aspect_AWS_rad = input.aspect_AWS_deg*(np.pi/180)
    P_AWS = input.P0*np.exp(-0.0289644*9.81*input.Elev_AWS/(8.31447*288.15))  # Pressure at Pyramid Station

    # Replace nan values with 0
    # Check nan values
    col_dict = {0:'year', 1:'month', 2:'day', 3:'hour', 4:'minute', 5:'Tair', 6:'RH', 7:'u', 14:'Rain', 10:'Sin',
                11:'Sout', 12:'Lin', 15:'Snow'}
    for n in [0,1,2,3,4,5,6,7,14,10,11,12,15]:
        nan_idx = np.where(np.isnan(met_data[:,n]) == True)[0]
        if len(nan_idx) > 0:
            print(col_dict[n], len(nan_idx), 'nan values replaced with zero')
            met_data[nan_idx, n] = 0
    # remove negative values of snowfall or rain
    neg_snow_idx = np.where(met_data[:,15] < 0)[0]
    if len(neg_snow_idx > 0):
        met_data[neg_snow_idx,15] = 0
        print(len(neg_snow_idx), 'negative snow values replaced with zero')
    neg_rain_idx = np.where(met_data[:,14] < 0)[0]
    if len(neg_rain_idx > 0):
        met_data[neg_rain_idx,14] = 0
        print(len(neg_rain_idx), 'negative rain values replaced with zero')

    # Select data
    year = met_data[:,0].astype(int)
    month = met_data[:,1].astype(int)
    day = met_data[:,2].astype(int)
    hour = met_data[:,3].astype(int)
    minute = met_data[:,4].astype(int)
    Tair_AWS = met_data[:,5] + 273.15 #celsius to kelvin
    RH_AWS = met_data[:,6] / 100 # percentage to decimal
    u_AWS_raw = met_data[:,7]
    Rain_AWS = met_data[:,14]/1000 # mm to meters
    Sin_AWS = met_data[:,10]
    Sout_AWS = met_data[:,11]
    Lin_AWS = met_data[:,12]
    Snow_AWS = met_data[:,15]

    Tair_AWS = Tair_AWS + input.lr_gcm * (input.debris_elev - input.Elev_AWS)

    # Albedo from AWS
    albedo_AWS = np.zeros(Sin_AWS.shape)
#    albedo_AWS[Sin_AWS > 0] = Sout_AWS[Sin_AWS > 0] / Sin_AWS[Sin_AWS > 0]
#    albedo_AWS[albedo_AWS > 1] = 1

    # Debris properties (Thickness, Surface roughness, Thermal conductivity)
    debris_properties = np.genfromtxt(input.debris_properties_fullfn, delimiter=',', skip_header=1)
    if input.experiment_no == 1:
        debris_thickness_all = np.array([debris_properties[0]])
        z0_random = np.array([debris_properties[1]])
        k_random = np.array([debris_properties[2]])
        albedo_AWS[:] = debris_properties[5]
    elif input.experiment_no == 2:
        debris_thickness_all = np.array([debris_properties[0,0]])
        z0_random = debris_properties[:,1]
        k_random = debris_properties[:,2]
#        Albedo_random = np.random.uniform(low=0.1, high=0.2, size=(input.mc_sims))
    elif input.experiment_no == 3:
        debris_thickness_all = np.array([0.01, 0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.15, 0.20, 0.30, 0.50, 1.0, 2.0, 
                                         3.0, 4.0, 5.0])
        z0_random = np.array([debris_properties[1]])
        k_random = np.array([debris_properties[2]])
        albedo_AWS[:] = debris_properties[5]
    elif input.experiment_no == 4:
        debris_thickness_all = np.array([0.01, 0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.15, 0.20, 0.30, 0.50, 1.0])
        z0_random = debris_properties[:,1]
        k_random = debris_properties[:,2]

#    # Add spinup
#    nsteps_spinup = int(input.spinup_days*24*60*60/input.delta_t)
#    met_data = np.concatenate((met_data[0:nsteps_spinup,:], met_data), axis=0)

    # Time information
    time_frac = hour + minute/60
    df_datetime = pd.to_datetime({'year': year, 'month': month, 'day': day, 'hour': hour, 'minute': minute})
    julian_day_of_year = np.array([int(x) for x in df_datetime.dt.strftime('%j').tolist()])
    nsteps = len(Tair_AWS)

    # ===== SHORTWAVE RADIATION ADJUSTMENTS (if any) =====
    # Assume that there is no adjustment for slope/aspect from AWS
    Sin_timeseries = Sin_AWS;

    # ===== LOOP THROUGH RELEVANT DEBRIS THICKNESS AND/OR MC SIMULATIONS =====
    for n_thickness in range(debris_thickness_all.shape[0]):
        debris_thickness = debris_thickness_all[n_thickness]
        # Height of each internal layer
        h = debris_thickness / 10
        # Number of internal calculation layers + 1 to include the surface layer
        N = int(debris_thickness/h + 1)

#        print('Debris thickness [m]:', debris_thickness)

        # Output dataset
        # Record melt, Ts, internal debris temperature, fluxes, and snow depth
        output_cns = ['Time', 'Melt [mwe]']
        # add internal temperature layers
        h_internal_cns = []
        for n_internal in range(N):
            if n_internal == 0:
                h_internal_cns.append('Ts [K]')
            elif n_internal == N-1:
                h_internal_cns.append('T_debris/ice [K]')
            else:
                h_internal_cns.append('T_' + str(int(np.round(n_internal * h * 1000)) / 1000) + ' [K]')
        for internal_cn in h_internal_cns:
            output_cns.append(internal_cn)
        # add fluxes and snow depth
        extra_cns = ['Rn [W m2]', 'LE [W m2]', 'H [W m2]', 'P [W m2]', 'Qc [W m2]', 'd_snow [m]']
        for extra_cn in extra_cns:
            output_cns.append(extra_cn)

        #%%
        for MC in range(k_random.shape[0]):
            if debug:
                print('  properties iteration ', MC)

            # Output file
            output_ds = pd.DataFrame(np.zeros((nsteps, len(output_cns))), columns=output_cns)
            output_ds['Time'] = df_datetime

            # Assume elevation and Sin are same as AWS
            Elevation_pixel = input.Elev_AWS
            Sin = Sin_timeseries
            long_deg_pixel = long_deg
            lat_deg_pixel = lat_deg
            slope_rad = 0
            aspect_rad = 0

            # Debris properties (Albedo, Surface roughness [m], Thermal Conductivity [W m-1 K-1])
#            Albedo = Albedo_random[MC]
            z0 = z0_random[MC]
            k = k_random[MC]

            # Additional properties
            # Turbulent heat flux transfer coefficient (neutral conditions)
            a_neutral_debris = input.Kvk**2/(np.log(input.za/z0))**2
            # Turbulent heat flux transfer coefficient (neutral condition)
            a_neutral_snow = input.Kvk**2/(np.log(input.za/input.z0_snow))**2
            # Adjust wind speed from sensor height to 2 m accounting for surface roughness
            u_AWS = u_AWS_raw*(np.log(2/z0)/(np.log(input.zw/z0)))
            # Pressure (barometric pressure formula)
            P = input.P0*np.exp(-0.0289644*9.81*Elevation_pixel/(8.31447*288.15))

            # Air temperature
            Tair = Tair_AWS - input.lapserate*(Elevation_pixel-input.Elev_AWS)
            # Snow [m]
            if input.option_snow_fromAWS == 1:
                snow = Snow_AWS.copy()
            else:
                snow = Rain_AWS.copy()
                snow[Tair > input.Tsnow_threshold] = 0
                Rain_AWS[Tair <= input.Tsnow_threshold] = 0

            # Solar information
            zenith_angle_rad, azimuth_angle_rad, rm_r2 = (
                    solar_calcs_NOAA(year, julian_day_of_year, time_frac, long_deg_pixel, lat_deg_pixel, nsteps))
            # Illumination angle / angle of Incidence b/w normal to grid slope at AWS and solar beam
            #  if slope & aspect are 0 degrees, then this is equal to the zenith angle
            ill_angle_rad = (np.arccos(np.cos(slope_rad) * np.cos(zenith_angle_rad) + np.sin(slope_rad) *
                             np.sin(zenith_angle_rad) * np.cos(azimuth_angle_rad - aspect_rad)))

            # ===== DEBRIS-COVERED GLACIER ENERGY BALANCE MODEL =====
            # Constant defined by Reid and Brock (2010) for Crank-Nicholson Scheme
            C = k * input.delta_t / (2 * input.row_d * input.c_d * h**2)
            # "Crank Nicholson Newton Raphson" Method for LE Rain
            # Compute Ts from surface energy balance model using Newton-Raphson Method at each time step and Td
            # at all points in debris layer
            Td = np.zeros((N, nsteps))
            a_Crank = np.zeros((N,nsteps))
            b_Crank = np.zeros((N,nsteps))
            c_Crank = np.zeros((N,nsteps))
            d_Crank = np.zeros((N,nsteps))
            A_Crank = np.zeros((N,nsteps))
            S_Crank = np.zeros((N,nsteps))
            n_iterations = np.zeros((nsteps))
            Ts_past = np.zeros((nsteps))
            LE = np.zeros((nsteps))
            Rn = np.zeros((nsteps))
            H_flux = np.zeros((nsteps))
            Qc = np.zeros((nsteps))
            P_flux = np.zeros((nsteps))
            dLE = np.zeros((nsteps))
            dRn = np.zeros((nsteps))
            dH_flux = np.zeros((nsteps))
            dQc = np.zeros((nsteps))
            dP_flux = np.zeros((nsteps))
            F_Ts = np.zeros((nsteps))
            dF_Ts = np.zeros((nsteps))
            Qc_ice = np.zeros((nsteps))
            Melt = np.zeros((nsteps))
            dsnow = np.zeros((nsteps))      # snow depth [mwe]
            tsnow = np.zeros((nsteps))      # snow temperature [K]
            snow_tau = np.zeros((nsteps))   # non-dimensional snow age

            # Initial values
            dsnow_t0 = 0
            tsnow_t0 = 273.15
            snow_tau_t0 = 0

            for i in np.arange(0,nsteps):

                Td[N-1,i] = 273.15

                if i > 0:
                    dsnow_t0 = dsnow[i-1]
                    tsnow_t0 = tsnow[i-1]
                    snow_tau_t0 = snow_tau[i-1]

                # Initially assume Ts = Tair, for all other time steps assume it's equal to previous Ts
                if i == 0:
                    Td[0,i] = Tair[i]
                else:
                    Td[0,i] = Td[0,i-1]

                # Calculate debris temperature profile for timestep i
                Td = CrankNicholson(Td, Tair, i, debris_thickness, N, h, C, a_Crank, b_Crank, c_Crank,
                                    d_Crank, A_Crank, S_Crank)

                # Surface energy fluxes
                (F_Ts[i], Rn[i], LE[i], H_flux[i], P_flux[i], Qc[i], dF_Ts[i], dRn[i], dLE[i], dH_flux[i],
                 dP_flux[i], dQc[i], dsnow[i], tsnow[i], snow_tau[i]) = (
                        calc_surface_fluxes(Td[:,i], Tair[i], RH_AWS[i], u_AWS[i], Sin[i], Lin_AWS[i],
                                            Rain_AWS[i], snow[i], P, albedo_AWS[i], k, a_neutral_debris,
                                            h, dsnow_t0, tsnow_t0, snow_tau_t0, ill_angle_rad[i],
                                            a_neutral_snow, debris_thickness,
                                            option_snow=input.option_snow,
                                            option_snow_fromAWS=input.option_snow_fromAWS))

                # Newton-Raphson method to solve for surface temperature
                while abs(Td[0,i] - Ts_past[i]) > 0.01 and n_iterations[i] < 100:
                    # CODE IMPROVEMENT HERE: n_iterations was improperly referenced

                    n_iterations[i] = n_iterations[i] + 1
                    Ts_past[i] = Td[0,i]
                    # max step size is 1 degree C
                    Td[0,i] = Ts_past[i] - F_Ts[i] /dF_Ts[i]
                    if (Td[0,i] - Ts_past[i]) > 1:
                        Td[0,i] = Ts_past[i] + 1
                    elif (Td[0,i] - Ts_past[i]) < -1:
                        Td[0,i] = Ts_past[i] - 1

                    # Debris temperature profile for timestep i
                    Td = CrankNicholson(Td, Tair, i, debris_thickness, N, h, C, a_Crank, b_Crank, c_Crank,
                                        d_Crank, A_Crank, S_Crank)

                    # Surface energy fluxes
                    (F_Ts[i], Rn[i], LE[i], H_flux[i], P_flux[i], Qc[i], dF_Ts[i], dRn[i], dLE[i], dH_flux[i],
                     dP_flux[i], dQc[i], dsnow[i], tsnow[i], snow_tau[i]) = (
                            calc_surface_fluxes(Td[:,i], Tair[i], RH_AWS[i], u_AWS[i], Sin[i], Lin_AWS[i],
                                                Rain_AWS[i], snow[i], P, albedo_AWS[i], k, a_neutral_debris,
                                                h, dsnow_t0, tsnow_t0, snow_tau_t0, ill_angle_rad[i],
                                                a_neutral_snow, debris_thickness,
                                                option_snow=input.option_snow,
                                                option_snow_fromAWS=input.option_snow_fromAWS))

                    if n_iterations[i] == 100:
                        Td[0,i] = (Td[0,i] + Ts_past[i]) / 2
                        print('Timestep ', i, 'maxed out at ', n_iterations[i], 'iterations.')

                Qc_ice[i] = k * (Td[N-2,i] - Td[N-1,i]) / h
                if Qc_ice[i] < 0:
                    Qc_ice[i] = 0
                Melt[i] = Qc_ice[i] * input.delta_t / (input.density_ice * input.Lf)
                #  meters of ice melt

            # Total melt [m ice]
            #  spinup has been removed
            melt_modeled_pixel = sum(Melt)

            if debug:
                print('  Melt[m ice]:', np.round(melt_modeled_pixel,3))


            # EXPORT OUTPUT
            output_ds['Melt [mwe]'] = Melt * input.density_ice / input.density_water
            output_ds.iloc[:,2:13] = np.transpose(Td)
            output_ds['Rn [W m2]'] = Rn
            output_ds['LE [W m2]'] = LE
            output_ds['H [W m2]'] = H_flux
            output_ds['P [W m2]'] = P_flux
            output_ds['Qc [W m2]'] = Qc
            output_ds['d_snow [m]'] = dsnow

            # create filepath if it does not exist
            output_fp = input.output_fp + 'exp' + str(input.experiment_no) + '/'
            if os.path.exists(output_fp) == False:
                os.makedirs(output_fp)
            # add debris thickness string
            debris_str = 'debris_' + str(int(debris_thickness*100)) + 'cm_'
            # add MC string
            if input.experiment_no == 1 or input.experiment_no == 3:
                mc_str = ''
            else:
                mc_str = 'MC' + str(MC) + '_'
            output_ds_fn = input.fn_prefix + debris_str + mc_str + date_start + '.csv'
            output_ds.to_csv(output_fp + output_ds_fn, index=False)
                
            melt_mwea = (output_ds['Melt [mwe]'].sum() / 
                         ((output_ds['Time'].values[-1] - output_ds['Time'].values[0])
                         .astype('timedelta64[D]').astype(int)/365.25))
            print(str(np.round(debris_thickness,2)) + ' m: ' + str(np.round(melt_mwea,2)) + ' mwea')
            
            #%%
#            ts_11 = output_ds.loc[347,'Ts [K]']
#            ts_12 = output_ds.loc[348,'Ts [K]']
#            print('Ts [C] @ 2013/06/15 11:45 AKST (' + str(np.round(debris_thickness,2)) + ' m):',
#                  np.round((ts_11 + 0.75 * (ts_12 - ts_11)) - 273.15,2), 
##                  'Tair [degC]:', np.round(Tair_AWS[1499] + 0.75*(Tair_AWS[1500] - Tair_AWS[1499]) - 273.15,2)
#                  )
            
            #%%

    print('\nProcessing time of :',time.time()-time_start, 's')