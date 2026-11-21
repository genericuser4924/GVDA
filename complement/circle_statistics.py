"""Calculate circular statistics without importing Qt or modifying the dialog."""

import math
import numpy as np
from .circular_median import circular_scores_compatible

def angular_distance_deg(a, b):
    distance = np.abs(a - b) % 360
    return np.minimum(distance, 360 - distance)


def calculate_circle_statistics(distances, azimuths, method, rounding, north, east, has_coordinates=False, station=None, progress=None):
    """Preserve the existing formulas and return values and presentation data."""
    distances = tuple(float(value) for value in distances)
    azimuths = tuple(float(value) for value in azimuths)
    north = tuple(float(value) for value in north)
    east = tuple(float(value) for value in east)
    if method not in ("Absolute", "Relative"):
        raise ValueError("Unsupported analysis method.")
    if not distances or len(distances) != len(azimuths):
        raise ValueError("Distance and azimuth series must be nonempty and aligned.")
    if len(north) != len(east) or len(north) != len(distances) + 1:
        raise ValueError("Coordinate and observation series are not aligned.")
    if not all(math.isfinite(value) for series in (distances, azimuths, north, east) for value in series):
        raise ValueError("Analysis inputs must contain only finite values.")
    red = int(rounding)
    if red != rounding or not 0 <= red <= 5:
        raise ValueError("Mode rounding must be an integer between zero and five.")
    act_met = method
    l_dist = l_dist_r = distances
    l_azimut = l_azimut_r = azimuths
    list_aci_o = list(azimuths)
    texts = {"num_d": f"Data Number: {len(distances)}"}
    enabled = {"red_mode_s": True}
    outliers_ready = False
    exist_coord = "Y" if has_coordinates else "N"
    sen_az_t = cos_az_t = sen_az_t2 = cos_az_t2 = 0
    datos = 0
    for lon_feat, azim_feat in zip(distances, azimuths):
        datos += 1
        cos_az = math.cos(azim_feat * math.pi / 180)
        sen_az = math.sin(azim_feat * math.pi / 180)
        sen_az_t = sen_az_t + sen_az
        cos_az_t = cos_az_t + cos_az
        cos_az2 = math.cos(2 * azim_feat * math.pi / 180)
        sen_az2 = math.sin(2 * azim_feat * math.pi / 180)
        sen_az_t2 = sen_az_t2 + sen_az2
        cos_az_t2 = cos_az_t2 + cos_az2
    az_med_t = 0.0
    if datos != 0:
        if cos_az_t == 0:
            az_med = math.pi / 2
        else:
            az_med = math.atan(sen_az_t / cos_az_t)
        if cos_az_t == 0 or sen_az_t == 0:
            if cos_az_t == 0:
                if sen_az_t > 0:
                    az_med = math.pi / 2
                elif sen_az_t == 0:
                    az_med = 0
                else:
                    az_med = math.pi / 2 + math.pi
            if sen_az_t == 0:
                if cos_az_t >= 0:
                    az_med = 0
                else:
                    az_med = math.pi
        else:
            if cos_az_t > 0 and sen_az_t > 0:
                az_med = az_med
            if cos_az_t < 0 and sen_az_t > 0:
                az_med = math.pi + az_med
            if cos_az_t < 0 and sen_az_t < 0:
                az_med = math.pi + az_med
            if cos_az_t > 0 and sen_az_t < 0:
                az_med = 2 * math.pi + az_med
    else:
        az_med = ''
    if datos != 0:
        if cos_az_t2 == 0:
            az_med2 = math.pi / 2
        else:
            az_med2 = math.atan(sen_az_t2 / cos_az_t2)
        if cos_az_t2 == 0 or sen_az_t2 == 0:
            if cos_az_t2 == 0:
                if sen_az_t2 > 0:
                    az_med2 = math.pi / 2
                else:
                    az_med2 = math.pi / 2 + math.pi
            elif cos_az_t2 > 0:
                az_med2 = 0
            else:
                az_med2 = math.pi
        else:
            if cos_az_t2 > 0 and sen_az_t2 > 0:
                az_med2 = az_med2
            if cos_az_t2 < 0 and sen_az_t2 > 0:
                az_med2 = math.pi + az_med2
            if cos_az_t2 < 0 and sen_az_t2 < 0:
                az_med2 = math.pi + az_med2
            if cos_az_t2 > 0 and sen_az_t2 < 0:
                az_med2 = 2 * math.pi + az_med2
    else:
        az_med2 = ''
    if len(list_aci_o) > 0:
        list_aci_ord, val_dm = circular_scores_compatible(
            list_aci_o, progress=progress
        )

        anterior = ''
        mediana = ''
        min_val_dm = val_dm[list_aci_ord[0]]
        for i in val_dm:
            if min_val_dm > val_dm[i]:
                min_val_dm = val_dm[i]
                mediana = i
        num_med = 0
        sum_med = 0
        for i in val_dm:
            if min_val_dm == val_dm[i]:
                sum_med += i
                num_med += 1
                ant_val = anterior
            anterior = i
        if num_med == 1:
            if len(list_aci_ord) % 2 == 0:
                cont = 0
                for i in list_aci_ord:
                    if sum_med == i:
                        cont += 1
                if cont == 1:
                    az_median = (sum_med + ant_val) / 2
                else:
                    az_median = sum_med / num_med
            else:
                az_median = sum_med / num_med
        else:
            az_median = sum_med / num_med
        clases = 360 * 10 ** red
        x_red = list()
        x_red.clear()
        cont = 0
        for i in list_aci_ord:
            x_red.append(round(i, red))
        frecuencias, extremos = np.histogram(x_red, bins=clases, range=(0, 360))
        f_moda = max(frecuencias)
        pos_max = 0
        cont = 0
        for i in frecuencias:
            if i == f_moda:
                pos_max = cont
                az_mode = (extremos[cont] + extremos[cont + 1]) / 2
            cont += 1
    else:
        az_median = ''
        az_mode = ''
    az_med_t = az_med * (180 / math.pi)
    minutos, grados = math.modf(az_med_t)
    segundos, minutos = math.modf(minutos * 60)
    segundos = round(segundos * 60, 2)
    cen_seg = str(round(segundos - int(segundos), 2))[1:4]
    resul_1 = f"Mean Azimuth: <b>{grados:.0f}° {int(minutos):02d}' {int(segundos):02d}" + cen_seg + "''</b>"
    texts['az_mean_t'] = resul_1
    minutos, grados = math.modf(az_median)
    segundos, minutos = math.modf(minutos * 60)
    segundos = round(segundos * 60, 2)
    cen_seg = str(round(segundos - int(segundos), 2))[1:4]
    resul_7 = f"Median Azimuth: <b>{grados:.0f}° {int(minutos):02d}' {int(segundos):02d}" + cen_seg + "''</b>"
    texts['az_median_t'] = resul_7
    mod_med = (cos_az_t ** 2 + sen_az_t ** 2) ** 0.5 / datos
    resul_2 = f'Mean resultant length: <b>{mod_med:.3f}</b>'
    texts['mod_med_t'] = resul_2
    if mod_med >= 0.5:
        minutos, grados = math.modf(round(az_mode, red))
        segundos, minutos = math.modf(minutos * 60)
        segundos = round(segundos * 60, 2)
        cen_seg = str(round(segundos - int(segundos), 2))[1:4]
        resul_7 = f"Mode Azimuth: <br><b>{grados:.0f}° {int(minutos):02d}' {int(segundos):02d}" + cen_seg + "''</b>"
    else:
        az_mode = ''
        resul_7 = 'Mode Azimuth: <br>Does not apply'
        enabled['red_mode_s'] = False
    texts['az_mode_t'] = resul_7
    mod_med2 = (cos_az_t2 ** 2 + sen_az_t2 ** 2) ** 0.5 / datos
    if az_mode != '':
        ed_azim = [az_med_t, az_median, round(az_mode, red)]
    else:
        ed_azim = [az_med_t, az_median]
    az_disc_mx = max(ed_azim)
    az_disc_mi = min(ed_azim)
    az_disc = angular_distance_deg(az_disc_mx, az_disc_mi)
    minutos, grados = math.modf(az_disc)
    segundos, minutos = math.modf(minutos * 60)
    segundos = round(segundos * 60, 2)
    cen_seg = str(round(segundos - int(segundos), 2))[1:4]
    resul_7 = f"Discrepancy: <b>{grados:.0f}° {int(minutos):02d}' {int(segundos):02d}" + cen_seg + "''</b>"
    texts['lb_disc'] = resul_7
    var_cir = 1 - mod_med
    resul_3 = f'Circular Variance: <b>{var_cir:.3f}</b>'
    texts['var_cir_t'] = resul_3
    var_ang = 2 * (1 - mod_med)
    resul_13 = f'Angular Variance: <b>{var_ang:.3f}</b>'
    texts['var_ang_t'] = resul_13
    des_cir = 180 / math.pi * (-2 * math.log(1 - var_cir)) ** 0.5
    minutos, grados = math.modf(des_cir)
    segundos, minutos = math.modf(minutos * 60)
    segundos = round(segundos * 60, 2)
    cen_seg = str(round(segundos - int(segundos), 2))[1:4]
    resul_4 = f"Circular Standard Deviation:<br> <b>{grados:.0f}° {int(minutos):02d}' {int(segundos):02d}" + cen_seg + "''</b>"
    texts['des_cir_t'] = resul_4
    az_med_i = az_med_t - des_cir
    if az_med_i < 0:
        az_med_i = 360 + az_med_i
    az_med_s = az_med_t + des_cir
    if az_med_s > 360:
        az_med_s = az_med_s - 360
    if mod_med < 0.53:
        par_k = 2 * mod_med + mod_med ** 3 + 5 / 6 * mod_med ** 5
    if mod_med >= 0.53 and mod_med < 0.85:
        par_k = -0.4 + 1.39 * mod_med + 0.43 / (1 - mod_med)
    if mod_med >= 0.85 and mod_med < 0.9:
        par_k = 1 / (2 * (1 - mod_med) + (1 - mod_med) ** 2 - (1 - mod_med) ** 3)
    if mod_med >= 0.9 and mod_med < 1:
        par_k = 1 / (2 * (1 - mod_med))
    if mod_med >= 1:
        par_k = float('inf')
    resul_4 = f'Von Mises Concentration Parameter:<br> <b>{par_k:.3f}</b>'
    texts['par_k_t'] = resul_4
    sum_ang = 0
    if act_met == 'Absolute':
        for i in range(len(l_dist)):
            azim_feat = l_azimut[i]
            sum_ang += abs(math.pi - abs(azim_feat * math.pi / 180 - az_med))
    elif act_met != '':
        for i in range(len(l_dist_r)):
            azim_feat = l_azimut_r[i]
            sum_ang += abs(math.pi - abs(azim_feat * math.pi / 180 - az_med))
    desv_ang = math.pi - sum_ang / datos
    desv_ang = desv_ang * 180 / math.pi
    minutos, grados = math.modf(desv_ang)
    segundos, minutos = math.modf(minutos * 60)
    segundos = round(segundos * 60, 2)
    cen_seg = str(round(segundos - int(segundos), 2))[1:4]
    resul_5 = f"Mean deviation:<br> <b>{grados:.0f}° {int(minutos):02d}' {int(segundos):02d}" + cen_seg + "''</b>"
    texts['des_ang_t'] = resul_5
    desv_ang_med = 180 / math.pi * (2 * (1 - mod_med)) ** 0.5
    minutos, grados = math.modf(desv_ang_med)
    segundos, minutos = math.modf(minutos * 60)
    segundos = round(segundos * 60, 2)
    cen_seg = str(round(segundos - int(segundos), 2))[1:4]
    resul_6 = f"Angular Deviation:<br> <b>{grados:.0f}° {int(minutos):02d}' {int(segundos):02d}" + cen_seg + "''</b>"
    texts['des_angm_t'] = resul_6
    if mod_med == 1:
        skew = 0
    else:
        skew = mod_med2 * math.sin(az_med2 - 2 * az_med) / (1 - mod_med) ** (3 / 2)
    resul_7 = f'Skewness Coefficient: <br> <b>{skew:.3f}</b>'
    texts['skew_t'] = resul_7
    if mod_med == 1:
        curt = float('inf')
    else:
        curt = (mod_med2 * math.cos(az_med2 - 2 * az_med) - mod_med ** 4) / (1 - mod_med) ** 2
    resul_8 = f'Kurtosis Coefficient: <br> <b>{curt:.3f}</b>'
    texts['curt_t'] = resul_8
    disp_cir = (1 - mod_med2) / (2 * mod_med ** 2)
    resul_9 = f'Circular Dispersion: <b>{disp_cir:.3f}</b>'
    texts['disp_cir_t'] = resul_9
    sum_error2 = 0
    sum_este = 0
    sum_norte = 0
    sum_long = 0
    if act_met == 'Absolute':
        for i in range(len(l_dist)):
            lon_feat = l_dist[i]
            azim_feat = l_azimut[i]
            norte = math.cos(azim_feat * math.pi / 180) * lon_feat
            este = math.sin(azim_feat * math.pi / 180) * lon_feat
            sum_norte += norte
            sum_este += este
            sum_long += lon_feat
    else:
        for i in range(len(l_dist_r)):
            lon_feat = l_dist_r[i]
            azim_feat = l_azimut_r[i]
            norte = math.cos(azim_feat * math.pi / 180) * lon_feat
            este = math.sin(azim_feat * math.pi / 180) * lon_feat
            sum_norte += norte
            sum_este += este
            sum_long += lon_feat
    norte_med = sum_norte / datos
    este_med = sum_este / datos
    long_med = sum_long / datos
    lt_dnorte = list()
    lt_deste = list()
    lt_dnorte.clear()
    lt_deste.clear()
    sum_de2 = 0
    sum_dn2 = 0
    sum_lon2 = 0
    if act_met == 'Absolute':
        for i in range(len(l_dist)):
            lon_feat = l_dist[i]
            azim_feat = l_azimut[i]
            dnorte = (math.cos(azim_feat * math.pi / 180) * lon_feat - norte_med) ** 2
            deste = (math.sin(azim_feat * math.pi / 180) * lon_feat - este_med) ** 2
            d_long = (lon_feat - long_med) ** 2
            sum_dn2 += dnorte
            sum_de2 += deste
            sum_lon2 += d_long
    else:
        for i in range(len(l_dist_r)):
            lon_feat = l_dist_r[i]
            azim_feat = l_azimut_r[i]
            dnorte = (math.cos(azim_feat * math.pi / 180) * lon_feat - norte_med) ** 2
            deste = (math.sin(azim_feat * math.pi / 180) * lon_feat - este_med) ** 2
            d_long = (lon_feat - long_med) ** 2
            sum_dn2 += dnorte
            sum_de2 += deste
            sum_lon2 += d_long
            lt_dnorte.append(dnorte)
            lt_deste.append(deste)
    if datos - 1 != 0:
        desv_sta_c = (0.5 * (sum(lt_dnorte) + sum(lt_deste)) / (datos - 1)) ** 0.5
    else:
        residual = 0
        desv_sta_c = 0
    if act_met == 'Absolute':
        texts['hde_t'] = ''
    else:
        resul_12 = f'Horizontal Standard Deviation: <b>{desv_sta_c:.7f}</b>'.rstrip('0').rstrip('.')
        texts['hde_t'] = resul_12
    if datos - 1 != 0:
        if datos < 167:
            m2 = (2.5055 + 4.6052 * math.log10(datos - 1)) ** 0.5
        else:
            m2 = 3.5
    else:
        m2 = 0
    if act_met == 'Absolute':
        texts['m2_t'] = ''
    else:
        resul_12 = f'Confidence multiplier: <b>{m2:.7f}</b>'.rstrip('0').rstrip('.')
        texts['m2_t'] = resul_12
    m2_desv = m2 * desv_sta_c
    if act_met == 'Absolute':
        texts['pot_out_t'] = ''
    else:
        resul_12 = f'Threshold criteria (>): <b>{m2_desv:.7f}</b>'.rstrip('0').rstrip('.')
        texts['pot_out_t'] = resul_12
    sum_out = 0
    list_outliers = list()
    list_residual = list()
    if act_met == 'Absolute':
        for i in range(len(l_dist)):
            lon_feat = l_dist[i]
            azim_feat = l_azimut[i]
            dnorte = (math.cos(azim_feat * math.pi / 180) * lon_feat - norte_med) ** 2
            deste = (math.sin(azim_feat * math.pi / 180) * lon_feat - este_med) ** 2
            res = (dnorte + deste) ** 0.5
            if res >= m2_desv:
                sum_out += 1
        texts['tot_out_t'] = ''
    else:
        for i in range(len(l_dist_r)):
            res = (lt_dnorte[i] + lt_deste[i]) ** 0.5
            if res >= m2_desv:
                sum_out += 1
                list_outliers.append(i)
                list_residual.append(res)
        outliers_ready = True
        resul_12 = f'Total Anomalies: <b>{sum_out:.0f}</b>'
        texts['tot_out_t'] = resul_12
    enabled['bt_ano'] = True
    if exist_coord == 'Y':
        enabled['bt_draw_ano'] = True

    enabled["bt_ano"] = sum_out > 0
    enabled["bt_draw_ano"] = sum_out > 0 and has_coordinates
    list_interv = []
    if outliers_ready and list_outliers:
        list_interv = calculate_outlier_intervals(north, east, list_outliers, station)
    locals_snapshot = locals()
    values = {name: locals_snapshot[name] for name in VALUE_NAMES}
    values["list_interv"] = list_interv
    return {"values": values, "texts": texts, "enabled": enabled, "outliers_ready": outliers_ready}


VALUE_NAMES = ('az_med', 'az_med_t', 'az_median', 'az_mode', 'az_disc', 'azim_feat', 'des_cir', 'var_ang', 'cen_seg', 'mod_med', 'var_cir', 'desv_ang', 'desv_ang_med', 'disp_cir', 'par_k', 'curt', 'skew', 'desv_sta_c', 'm2_desv', 'sum_out', 'az_med_i', 'az_med_s', 'norte_med', 'este_med', 'm2', 'list_outliers', 'list_residual', 'list_aci_o', 'datos')


def calculate_outlier_intervals(d_n, d_e, list_outliers, station=None):
    list_interv = []
    north_count = len(d_n)
    east_count = len(d_e)
    if north_count != east_count:
        raise ValueError(f'Coordinate series are not aligned. Station={station!r}; len(d_n)={north_count}; len(d_e)={east_count}; len(l_dist_r)={len(d_n) - 1}; len(l_azimut_r)={len(d_n) - 1}.')
    invalid_index = next((index for index in list_outliers if index < 0 or index >= north_count), None)
    if invalid_index is not None:
        raise ValueError(f'An outlier index does not belong to the active coordinates. Station={station!r}; index={invalid_index}; coordinate_count={north_count}; len(l_dist_r)={len(d_n) - 1}; len(l_azimut_r)={len(d_n) - 1}.')
    k = 0
    idx = 0
    for out in range(len(list_outliers) + 1):
        # No increment remains after the last coordinate.
        if k >= north_count - 1:
            break
        list_az = list()
        fin = list_outliers[out] if idx <= len(list_outliers) - 1 else len(d_n) - 1
        if k == fin:
            fin += 1
            cont = 0
        else:
            cont = 1
        for j in range(k, fin):
            n_ref = float(d_n[k])
            e_ref = float(d_e[k])
            delta_n_int = float(d_n[j + 1]) - n_ref
            delta_e_int = float(d_e[j + 1]) - e_ref
            az_rad = math.degrees(math.atan2(delta_e_int, delta_n_int)) % 360
            list_az.append(az_rad)
            cont += 1
        list_interv.append(list_az.copy())
        k += cont
        idx += 1
    return list_interv


def _format_mode_angle(value):
    """Preserve the existing degree-minute-second formatting."""
    minutes, degrees = math.modf(value)
    seconds, minutes = math.modf(minutes * 60)
    seconds = round(seconds * 60, 2)

    fraction = str(
        round(seconds - int(seconds), 2)
    )[1:4]

    return (
        f"{degrees:.0f}° {int(minutes):02d}' "
        f"{int(seconds):02d}" + fraction + "''"
    )


def calculate_mode_update(
    azimuths,
    rounding,
    mean_degrees,
    median_degrees,
    resultant_length,
):
    """Recalculate only mode and its dependent discrepancy."""
    red = int(rounding)

    if red != rounding or not 0 <= red <= 5:
        raise ValueError(
            "Mode rounding must be an integer between zero and five."
        )

    if resultant_length >= 0.5:
        rounded = [
            round(float(angle), red)
            for angle in azimuths
        ]

        if not rounded:
            raise ValueError(
                "No azimuths are available for mode calculation."
            )

        frequencies, edges = np.histogram(
            rounded,
            bins=360 * (10 ** red),
            range=(0, 360),
        )

        # Preserve the existing last-bin tie-breaking rule.
        index = int(
            np.flatnonzero(
                frequencies == frequencies.max()
            )[-1]
        )

        mode = (
            edges[index] + edges[index + 1]
        ) / 2

        displayed_mode = round(mode, red)

        mode_text = (
            "Mode Azimuth: <br><b>"
            + _format_mode_angle(displayed_mode)
            + "</b>"
        )

        directions = [
            mean_degrees,
            median_degrees,
            displayed_mode,
        ]

    else:
        mode = ""
        mode_text = "Mode Azimuth: <br>Does not apply"

        directions = [
            mean_degrees,
            median_degrees,
        ]

    distance = (
        abs(max(directions) - min(directions))
        % 360
    )

    discrepancy = min(
        distance,
        360 - distance,
    )

    discrepancy_text = (
        "Discrepancy: <b>"
        + _format_mode_angle(discrepancy)
        + "</b>"
    )

    return {
        "values": {
            "az_mode": mode,
            "az_disc": discrepancy,
        },
        "texts": {
            "az_mode_t": mode_text,
            "lb_disc": discrepancy_text,
        },
    }
