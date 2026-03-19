"""
Generador de reportes HTML para resultados de simulaciones YAFS

Crea un reporte interactivo con gráficos y tablas a partir de los
archivos CSV generados por las simulaciones.

Uso:
    python generate_report.py results_edge_fog_cloud
"""

import sys
import pandas as pd
from pathlib import Path
import base64
from datetime import datetime


def read_image_base64(image_path):
    """Convierte imagen a base64 para embedding en HTML"""
    if not Path(image_path).exists():
        return None
    with open(image_path, 'rb') as f:
        return base64.b64encode(f.read()).decode()


def generate_html_report(results_dir):
    """Genera un reporte HTML completo"""
    
    results_path = Path(results_dir)
    if not results_path.exists():
        print(f"❌ Error: Directorio {results_dir} no existe")
        print(f"   Primero ejecuta una simulación")
        return False
    
    # Leer datos
    trace_file = results_path / "sim_trace.csv"
    link_file = results_path / "sim_trace_link.csv"
    
    if not trace_file.exists():
        print(f"❌ Error: No se encontró {trace_file}")
        return False
    
    df = pd.read_csv(trace_file)
    df_links = pd.read_csv(link_file) if link_file.exists() else pd.DataFrame()
    
    # Buscar imágenes
    images = list(results_path.glob("*.png"))
    
    # Generar HTML
    html = generate_html_content(df, df_links, images, results_dir)
    
    # Guardar
    output_file = results_path / "report.html"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"✅ Reporte generado: {output_file}")
    print(f"   Abre en navegador: file://{output_file.absolute()}")
    
    return True


def generate_html_content(df, df_links, images, results_dir):
    """Genera el contenido HTML del reporte"""
    
    # Calcular métricas
    total_messages = len(df)
    total_links = len(df_links)
    report_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    apps = df['app'].unique() if 'app' in df.columns else []
    
    # Estadísticas por aplicación
    app_stats = []
    for app_id in apps:
        app_df = df[df['app'] == app_id]
        if len(app_df) > 0:
            latency = (app_df['time_out'] - app_df['time_in']).mean()
            app_stats.append({
                'app': app_id,
                'messages': len(app_df),
                'latency': f"{latency:.2f}"
            })
    
    # Nodos más activos
    if 'TOPO.dst' in df.columns:
        top_nodes = df['TOPO.dst'].value_counts().head(10)
        top_nodes_html = "".join([
            f"<tr><td>Node {node}</td><td class=\"num\">{count}</td></tr>"
            for node, count in top_nodes.items()
        ])
    else:
        top_nodes_html = "<tr><td colspan='2'>Not available</td></tr>"
    
    # App stats HTML
    app_stats_html = "".join([
        f"<tr><td>App {s['app']}</td><td class=\"num\">{s['messages']}</td><td class=\"num\">{s['latency']}</td></tr>"
        for s in app_stats
    ])
    
    # Imágenes
    images_html = ""
    for img_path in images:
        img_base64 = read_image_base64(img_path)
        if img_base64:
            images_html += f"""
            <figure class="image-container">
                <img src="data:image/png;base64,{img_base64}" alt="{img_path.name}">
                <figcaption>{img_path.stem.replace('_', ' ').title()}</figcaption>
            </figure>
            """
    
    # HTML completo
    html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>YAFS Simulation Report - {results_dir}</title>
    <style>
        :root {{
            --paper-bg: #f4f5f7;
            --panel-bg: #ffffff;
            --header-bg: #1f2933;
            --text-main: #1f2933;
            --text-muted: #52606d;
            --border-light: #d9dde2;
            --accent: #2e5d94;
            --table-header: #eef1f4;
        }}

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: Georgia, 'Times New Roman', Times, serif;
            color: var(--text-main);
            background: radial-gradient(circle at top right, #ffffff 0%, var(--paper-bg) 50%, #eceff2 100%);
            padding: 24px;
            line-height: 1.5;
        }}
        
        .container {{
            max-width: 1100px;
            margin: 0 auto;
            background: var(--panel-bg);
            border: 1px solid var(--border-light);
            box-shadow: 0 6px 20px rgba(15, 23, 42, 0.08);
            overflow: hidden;
        }}
        
        .header {{
            background: var(--header-bg);
            color: #ffffff;
            padding: 30px 34px;
            text-align: center;
            border-bottom: 3px solid var(--accent);
        }}
        
        .header h1 {{
            font-size: 2rem;
            font-weight: 600;
            letter-spacing: 0.02em;
            margin-bottom: 8px;
        }}
        
        .header p {{
            font-size: 1rem;
            opacity: 0.92;
        }}
        
        .content {{
            padding: 30px 34px;
        }}
        
        .metric-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 14px;
            margin-bottom: 30px;
        }}
        
        .metric-card {{
            background: #ffffff;
            border: 1px solid var(--border-light);
            border-left: 4px solid var(--accent);
            padding: 18px 20px;
        }}
        
        .metric-card h3 {{
            font-size: 0.82rem;
            color: var(--text-muted);
            margin-bottom: 8px;
            text-transform: none;
            letter-spacing: 0;
        }}
        
        .metric-card .value {{
            font-family: 'Courier New', Courier, monospace;
            font-size: 1.9rem;
            font-weight: 700;
        }}
        
        .section {{
            margin-bottom: 30px;
        }}
        
        .section h2 {{
            color: var(--text-main);
            border-bottom: 1px solid var(--border-light);
            padding-bottom: 8px;
            margin-bottom: 14px;
            font-size: 1.3rem;
            font-weight: 600;
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
            font-size: 0.95rem;
            border: 1px solid var(--border-light);
        }}
        
        th {{
            background: var(--table-header);
            color: var(--text-main);
            border-top: 1px solid var(--border-light);
            border-bottom: 1px solid var(--border-light);
            padding: 10px 12px;
            text-align: left;
            font-weight: 600;
        }}
        
        td {{
            padding: 9px 12px;
            border-bottom: 1px solid var(--border-light);
        }}
        
        tbody tr:nth-child(even) {{
            background-color: #fafbfc;
        }}
        
        .num {{
            text-align: right;
            font-family: 'Courier New', Courier, monospace;
        }}

        .image-container {{
            margin: 30px 0;
            text-align: center;
        }}
        
        .image-container img {{
            max-width: 100%;
            height: auto;
            border: 1px solid var(--border-light);
            padding: 8px;
            background: #ffffff;
        }}
        
        .image-container figcaption {{
            margin-top: 9px;
            color: var(--text-muted);
            font-size: 0.9rem;
            font-style: italic;
        }}
        
        .footer {{
            background: #f7f8fa;
            border-top: 1px solid var(--border-light);
            padding: 24px;
            text-align: center;
            color: var(--text-muted);
            font-size: 0.95rem;
        }}
        
        .footer a {{
            color: var(--accent);
            text-decoration: none;
        }}
        
        .footer a:hover {{
            text-decoration: underline;
        }}
        
        .badge {{
            display: inline-block;
            padding: 4px 9px;
            border-radius: 2px;
            border: 1px solid var(--border-light);
            background: #ffffff;
            color: var(--text-main);
            font-size: 0.84rem;
            margin: 4px;
            font-family: 'Courier New', Courier, monospace;
        }}

        .muted-note {{
            margin-top: 12px;
            color: var(--text-muted);
            font-size: 0.95rem;
        }}
        
        @media print {{
            body {{
                background: white;
                padding: 0;
            }}
            
            .container {{
                box-shadow: none;
                border: none;
            }}
            
            .metric-card {{
                break-inside: avoid;
            }}
        }}

        @media (max-width: 768px) {{
            body {{
                padding: 10px;
            }}

            .header,
            .content {{
                padding: 20px;
            }}

            .header h1 {{
                font-size: 1.5rem;
            }}

            .metric-card .value {{
                font-size: 1.6rem;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>YAFS Simulation Report</h1>
            <p>{results_dir.replace('_', ' ').title()}</p>
            <p style="margin-top: 6px; font-size: 0.9rem;">Generated on {report_timestamp}</p>
        </div>
        
        <div class="content">
            <!-- Core metrics -->
            <div class="metric-grid">
                <div class="metric-card">
                    <h3>Total Messages</h3>
                    <div class="value">{total_messages:,}</div>
                </div>
                <div class="metric-card">
                    <h3>Network Transmissions</h3>
                    <div class="value">{total_links:,}</div>
                </div>
                <div class="metric-card">
                    <h3>Applications</h3>
                    <div class="value">{len(apps)}</div>
                </div>
                <div class="metric-card">
                    <h3>Active Nodes</h3>
                    <div class="value">{df['TOPO.dst'].nunique() if 'TOPO.dst' in df.columns else 'N/A'}</div>
                </div>
            </div>
            
            <!-- Application statistics -->
            <div class="section">
                <h2>Application Statistics</h2>
                <table>
                    <thead>
                        <tr>
                            <th>Application</th>
                            <th class="num">Processed Messages</th>
                            <th class="num">Average Latency</th>
                        </tr>
                    </thead>
                    <tbody>
                        {app_stats_html if app_stats_html else '<tr><td colspan="3">No data available</td></tr>'}
                    </tbody>
                </table>
            </div>
            
            <!-- Top nodes -->
            <div class="section">
                <h2>Top 10 Most Active Nodes</h2>
                <table>
                    <thead>
                        <tr>
                            <th>Node</th>
                            <th class="num">Processed Messages</th>
                        </tr>
                    </thead>
                    <tbody>
                        {top_nodes_html}
                    </tbody>
                </table>
            </div>
            
            <!-- Visualizations -->
            {f'<div class="section"><h2>Figures and Visualizations</h2>{images_html}</div>' if images_html else ''}
            
            <!-- Data details -->
            <div class="section">
                <h2>Data Sources</h2>
                <p>
                    <span class="badge">sim_trace.csv: {total_messages} records</span>
                    <span class="badge">sim_trace_link.csv: {total_links} records</span>
                </p>
                <p class="muted-note">
                    For custom analysis, open the CSV files with pandas, spreadsheets, or data analysis tools.
                </p>
            </div>
        </div>
        
        <div class="footer">
            <p><strong>YAFS</strong> - Yet Another Fog Simulator</p>
            <p style="margin-top: 10px;">
                <a href="https://yafs.readthedocs.io" target="_blank">Documentation</a> |
                <a href="https://github.com/acsicuib/YAFS" target="_blank">GitHub</a>
            </p>
            <p style="margin-top: 10px; font-size: 0.9em;">
                Generated by generate_report.py
            </p>
        </div>
    </div>
</body>
</html>
"""
    
    return html


def main():
    if len(sys.argv) < 2:
        print("Uso: python generate_report.py <directorio_resultados>")
        print("\nEjemplo:")
        print("  python generate_report.py results_edge_fog_cloud")
        print("\nDirectorios disponibles:")
        
        for path in Path('.').glob('results_*'):
            if path.is_dir():
                print(f"  - {path.name}")
        
        return 1
    
    results_dir = sys.argv[1]
    
    print("="*60)
    print("  Generador de Reportes HTML - YAFS")
    print("="*60)
    print()
    
    success = generate_html_report(results_dir)
    
    if success:
        print()
        print("="*60)
        print("✅ Reporte generado exitosamente")
        print("="*60)
        return 0
    else:
        print()
        print("="*60)
        print("❌ Error al generar reporte")
        print("="*60)
        return 1


if __name__ == '__main__':
    sys.exit(main())
