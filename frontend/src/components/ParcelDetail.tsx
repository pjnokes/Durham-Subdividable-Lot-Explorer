import { useEffect, useState, useRef, useCallback } from "react";
import { fetchParcelDetail, type ParcelDetail as PD } from "../api/client";

interface Props {
  parcelId: number | null;
  onClose: () => void;
}

function Badge({
  children,
  color,
}: {
  children: React.ReactNode;
  color: string;
}) {
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded text-xs font-semibold ${color}`}
    >
      {children}
    </span>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between items-start py-1.5">
      <span className="text-slate-400 text-sm">{label}</span>
      <span className="text-white text-sm text-right max-w-[55%]">
        {value}
      </span>
    </div>
  );
}

function isValidRedfinUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" && parsed.hostname.endsWith("redfin.com");
  } catch {
    return false;
  }
}

function ListingSection({ listing }: { listing: NonNullable<PD["listing"]> }) {
  const [showEmbed, setShowEmbed] = useState(false);
  const safeRedfinUrl = listing.redfin_url && isValidRedfinUrl(listing.redfin_url) ? listing.redfin_url : null;

  const pricePerSqft =
    listing.list_price && listing.sqft
      ? Math.round(listing.list_price / listing.sqft)
      : null;

  return (
    <>
      <hr className="border-slate-700" />
      <div>
        <h4 className="text-xs font-semibold text-red-400 uppercase tracking-wider mb-3">
          Active Listing
        </h4>

        {/* Price hero */}
        {listing.list_price && (
          <div className="text-center mb-3">
            <span className="text-2xl font-bold text-white">
              ${Math.round(listing.list_price).toLocaleString()}
            </span>
            {pricePerSqft && (
              <span className="text-slate-400 text-sm ml-2">
                (${pricePerSqft}/sf)
              </span>
            )}
          </div>
        )}

        {/* Quick stats row */}
        <div className="flex justify-around text-center mb-3 py-2 bg-slate-800/60 rounded-lg">
          {listing.beds != null && (
            <div>
              <div className="text-white font-semibold text-sm">{listing.beds}</div>
              <div className="text-slate-500 text-[10px] uppercase">beds</div>
            </div>
          )}
          {listing.baths != null && (
            <div>
              <div className="text-white font-semibold text-sm">{listing.baths}</div>
              <div className="text-slate-500 text-[10px] uppercase">baths</div>
            </div>
          )}
          {listing.sqft != null && (
            <div>
              <div className="text-white font-semibold text-sm">{listing.sqft.toLocaleString()}</div>
              <div className="text-slate-500 text-[10px] uppercase">sqft</div>
            </div>
          )}
          {listing.year_built != null && (
            <div>
              <div className="text-white font-semibold text-sm">{listing.year_built}</div>
              <div className="text-slate-500 text-[10px] uppercase">built</div>
            </div>
          )}
        </div>

        {/* Detail rows */}
        {listing.days_on_market != null && (
          <Row
            label="Days on Market"
            value={
              <span className={listing.days_on_market > 30 ? "text-amber-400" : "text-white"}>
                {listing.days_on_market}
              </span>
            }
          />
        )}
        {listing.property_type && (
          <Row label="Type" value={listing.property_type} />
        )}
        {listing.lot_size_sqft != null && listing.lot_size_sqft > 0 && (
          <Row
            label="Lot Size (listing)"
            value={`${listing.lot_size_sqft.toLocaleString()} sf`}
          />
        )}
        {listing.hoa_month != null && listing.hoa_month > 0 && (
          <Row
            label="HOA"
            value={`$${Math.round(listing.hoa_month).toLocaleString()}/mo`}
          />
        )}
        {listing.mls_number && (
          <Row label="MLS#" value={listing.mls_number} />
        )}

        {/* Action buttons */}
        {safeRedfinUrl && (
          <div className="mt-3 space-y-2">
            <a
              href={safeRedfinUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="block w-full text-center bg-red-600 hover:bg-red-500 text-white py-2.5 rounded-lg text-sm font-medium transition-colors"
            >
              View Full Listing on Redfin
            </a>
            <button
              onClick={() => setShowEmbed((v) => !v)}
              className="block w-full text-center bg-slate-700 hover:bg-slate-600 text-slate-200 py-2 rounded-lg text-xs font-medium transition-colors hidden md:block"
            >
              {showEmbed ? "Hide Preview" : "Show Listing Preview"}
            </button>
          </div>
        )}

        {/* Embedded Redfin page — desktop only */}
        {showEmbed && safeRedfinUrl && (
          <div className="mt-3 rounded-lg overflow-hidden border border-slate-600 hidden md:block">
            <iframe
              src={safeRedfinUrl}
              title="Redfin listing preview"
              className="w-full bg-white"
              style={{ height: 480 }}
              sandbox="allow-scripts allow-popups"
              loading="lazy"
            />
            <div className="bg-slate-800 px-3 py-1.5 text-[10px] text-slate-400 flex justify-between items-center">
              <span>Preview may be limited by Redfin</span>
              <a
                href={safeRedfinUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-red-400 hover:text-red-300"
              >
                Open full page
              </a>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

const SNAP_COLLAPSED = 0.45;
const SNAP_EXPANDED = 0.9;

export default function ParcelDetailPanel({ parcelId, onClose }: Props) {
  const [detail, setDetail] = useState<PD | null>(null);
  const [loading, setLoading] = useState(false);
  const [sheetHeight, setSheetHeight] = useState(SNAP_COLLAPSED);
  const dragRef = useRef<{ startY: number; startHeight: number } | null>(null);
  const sheetRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!parcelId) {
      setDetail(null);
      return;
    }
    setLoading(true);
    setSheetHeight(SNAP_COLLAPSED);
    fetchParcelDetail(parcelId)
      .then(setDetail)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [parcelId]);

  const handleDragStart = useCallback((clientY: number) => {
    dragRef.current = { startY: clientY, startHeight: sheetHeight };
  }, [sheetHeight]);

  const handleDragMove = useCallback((clientY: number) => {
    if (!dragRef.current) return;
    const deltaRatio = (dragRef.current.startY - clientY) / window.innerHeight;
    const newHeight = Math.max(0.15, Math.min(SNAP_EXPANDED, dragRef.current.startHeight + deltaRatio));
    setSheetHeight(newHeight);
  }, []);

  const handleDragEnd = useCallback(() => {
    if (!dragRef.current) return;
    dragRef.current = null;
    setSheetHeight((h) => {
      if (h < 0.25) {
        onClose();
        return SNAP_COLLAPSED;
      }
      return h > (SNAP_COLLAPSED + SNAP_EXPANDED) / 2 ? SNAP_EXPANDED : SNAP_COLLAPSED;
    });
  }, [onClose]);

  const onTouchStart = useCallback((e: React.TouchEvent) => {
    handleDragStart(e.touches[0].clientY);
  }, [handleDragStart]);

  const onTouchMove = useCallback((e: React.TouchEvent) => {
    handleDragMove(e.touches[0].clientY);
  }, [handleDragMove]);

  const onTouchEnd = useCallback(() => {
    handleDragEnd();
  }, [handleDragEnd]);

  if (!parcelId) return null;

  const content = (
    <>
      {loading ? (
        <div className="p-5 space-y-3">
          {[...Array(8)].map((_, i) => (
            <div
              key={i}
              className="h-5 bg-slate-700/50 rounded animate-pulse"
            />
          ))}
        </div>
      ) : detail ? (
        <div className="p-5 space-y-4">
          {/* Address & PIN */}
          <div>
            <h3 className="text-lg font-bold text-white">
              {detail.address || detail.owner_mail_1 || "No address on file"}
            </h3>
            <p className="text-sm text-slate-400">PIN: {detail.pin}</p>
            {!detail.address && detail.owner_mail_1 && (
              <p className="text-xs text-amber-400/80 mt-0.5">
                (using mailing address — no site address on file)
              </p>
            )}
          </div>

          {/* Highlight banner for subdividable + for sale */}
          {detail.listing && detail.analysis?.is_subdividable && (
            <div className="p-2.5 bg-amber-500/15 border border-amber-500/40 rounded-lg text-center">
              <span className="text-amber-400 font-bold text-sm tracking-wide">
                SUBDIVIDABLE + FOR SALE
              </span>
              {detail.listing.list_price && (
                <span className="text-amber-300 font-semibold text-sm ml-2">
                  · ${Math.round(detail.listing.list_price).toLocaleString()}
                </span>
              )}
            </div>
          )}

          {/* Status badges */}
          <div className="flex gap-2 flex-wrap">
            {detail.listing && !detail.analysis?.is_subdividable && (
              <Badge color="bg-red-500/20 text-red-400">
                For Sale
              </Badge>
            )}
            {detail.analysis && (
              <>
                {detail.analysis.is_subdividable ? (
                <Badge color="bg-green-500/20 text-green-400">
                  Subdividable
                </Badge>
              ) : (
                <Badge color="bg-slate-600/50 text-slate-300">
                  Not Subdividable
                </Badge>
              )}
              {detail.analysis.subdivision_type && (
                <Badge color="bg-blue-500/20 text-blue-400">
                  {detail.analysis.subdivision_type.replace("_", " ")}
                </Badge>
              )}
              {detail.analysis.num_possible_lots &&
                detail.analysis.num_possible_lots > 1 && (
                  <Badge color="bg-purple-500/20 text-purple-400">
                    {detail.analysis.num_possible_lots} lots
                  </Badge>
                )}
              {detail.analysis.is_corner_lot && (
                <Badge color="bg-blue-500/20 text-blue-400">
                  Corner Lot
                </Badge>
              )}
              {detail.analysis.num_street_frontages === 1 && (
                <Badge color="bg-yellow-500/20 text-yellow-400">
                  Interior (flag lot only)
                </Badge>
              )}
              </>
            )}
          </div>

          {/* Listing Info */}
          {detail.listing && <ListingSection listing={detail.listing} />}

          <hr className="border-slate-700" />

          {/* Property Info */}
          <div>
            <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
              Property
            </h4>
            <Row label="Owner" value={detail.property_owner || "—"} />
            <Row label="Zoning" value={detail.zoning} />
            <Row
              label="Lot Area"
              value={`${Math.round(detail.area_sqft).toLocaleString()} sf (${detail.acreage?.toFixed(2) || "—"} ac)`}
            />
            <Row
              label="Assessed Value"
              value={
                detail.total_prop_value
                  ? `$${Math.round(detail.total_prop_value).toLocaleString()}`
                  : "—"
              }
            />
            <Row
              label="Land Value"
              value={
                detail.total_land_value
                  ? `$${Math.round(detail.total_land_value).toLocaleString()}`
                  : "—"
              }
            />
            <Row
              label="Bldg Value"
              value={
                detail.total_bldg_value
                  ? `$${Math.round(detail.total_bldg_value).toLocaleString()}`
                  : "—"
              }
            />
            <Row
              label="Heated Area"
              value={
                detail.heated_area
                  ? `${detail.heated_area.toLocaleString()} sf`
                  : "—"
              }
            />
          </div>

          {/* Analysis */}
          {detail.analysis && (
            <>
              <hr className="border-slate-700" />
              <div>
                <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
                  Subdivision Analysis
                </h4>
                <Row
                  label="Status"
                  value={
                    detail.analysis.is_subdividable ? (
                      <span className="text-green-400 font-semibold">Subdividable</span>
                    ) : (
                      <span className="text-slate-400">Not Subdividable</span>
                    )
                  }
                />
                <Row
                  label="Type"
                  value={
                    detail.analysis.subdivision_type?.replace("_", " ") || "—"
                  }
                />
                <Row
                  label="Possible Lots"
                  value={detail.analysis.num_possible_lots || "—"}
                />
                <Row
                  label="Max Structure"
                  value={
                    detail.analysis.max_structure_footprint_sqft
                      ? `${Math.round(detail.analysis.max_structure_footprint_sqft).toLocaleString()} sf`
                      : "—"
                  }
                />
                <Row
                  label="Street Access"
                  value={
                    detail.analysis.num_street_frontages != null
                      ? `${detail.analysis.num_street_frontages} side${detail.analysis.num_street_frontages !== 1 ? "s" : ""} ${detail.analysis.is_corner_lot ? "(corner)" : detail.analysis.num_street_frontages === 1 ? "(interior)" : ""}`
                      : "—"
                  }
                />
                <Row
                  label="Confidence"
                  value={
                    detail.analysis.confidence_score
                      ? `${(detail.analysis.confidence_score * 100).toFixed(0)}%`
                      : "—"
                  }
                />
                {detail.analysis.existing_structure_conflict && (
                  <div className="mt-2 p-2 bg-amber-500/10 border border-amber-500/30 rounded text-xs text-amber-400">
                    ⚠ Existing structure may conflict with proposed lot lines
                  </div>
                )}
                {detail.analysis.notes && (
                  <div className="mt-2 p-2 bg-slate-800 rounded text-xs text-slate-300">
                    {detail.analysis.notes}
                  </div>
                )}
              </div>
            </>
          )}

          {/* Mailing Info */}
          {detail.owner_mail_1 && (
            <>
              <hr className="border-slate-700" />
              <div>
                <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
                  Owner Mailing Address
                </h4>
                <p className="text-sm text-white">{detail.owner_mail_1}</p>
                <p className="text-sm text-white">
                  {[
                    detail.owner_mail_city,
                    detail.owner_mail_state,
                    detail.owner_mail_zip,
                  ]
                    .filter(Boolean)
                    .join(", ")}
                </p>
              </div>
            </>
          )}

          {/* Safe area for bottom sheet on mobile */}
          <div className="h-6 md:h-0" />
        </div>
      ) : (
        <div className="p-5 text-slate-400 text-sm">No data available.</div>
      )}
    </>
  );

  return (
    <>
      {/* Desktop: right sidebar */}
      <div className="hidden md:block absolute top-10 right-0 z-30 w-96 h-[calc(100%-40px)] bg-slate-900/95 backdrop-blur border-l border-slate-700 shadow-2xl overflow-y-auto transition-transform duration-300">
        <div className="sticky top-0 bg-slate-900/95 backdrop-blur border-b border-slate-700 px-5 py-3 flex justify-between items-center">
          <h2 className="font-semibold text-white">Parcel Detail</h2>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white text-xl leading-none transition-colors"
          >
            ✕
          </button>
        </div>
        {content}
      </div>

      {/* Mobile: bottom sheet */}
      <div
        ref={sheetRef}
        className="md:hidden fixed inset-x-0 bottom-0 z-50 bg-slate-900/[0.98] backdrop-blur-lg rounded-t-2xl shadow-2xl border-t border-slate-700 transition-[height] duration-200"
        style={{ height: `${sheetHeight * 100}vh` }}
      >
        {/* Drag handle */}
        <div
          className="flex justify-center pt-3 pb-1 cursor-grab active:cursor-grabbing touch-none"
          onTouchStart={onTouchStart}
          onTouchMove={onTouchMove}
          onTouchEnd={onTouchEnd}
          onMouseDown={(e) => handleDragStart(e.clientY)}
          onMouseMove={(e) => { if (dragRef.current) handleDragMove(e.clientY); }}
          onMouseUp={handleDragEnd}
        >
          <div className="w-10 h-1 bg-slate-600 rounded-full" />
        </div>

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-2 border-b border-slate-700">
          <h2 className="font-semibold text-white text-sm">Parcel Detail</h2>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white text-lg leading-none transition-colors p-1"
          >
            ✕
          </button>
        </div>

        <div className="overflow-y-auto" style={{ height: `calc(${sheetHeight * 100}vh - 4rem)` }}>
          {content}
        </div>
      </div>
    </>
  );
}
